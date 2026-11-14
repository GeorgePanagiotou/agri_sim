"""Download native HLSL30 v2 windows for the Evia sowing pilot from the NASA data mirror.

The raw cache contains only cropped windows. Outputs contain one observation per
UTC day, the unmodified quality byte, and scaled B03/B04/B05 reflectance.
"""

import argparse
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
import time
from urllib.parse import urlsplit
from uuid import uuid4

import certifi
import numpy as np
import pandas as pd
import rasterio
import requests
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform
from rasterio.windows import Window

if __package__:
    from .config import PROC, RAW, REPO, SOWING_LAT, SOWING_LON, SOWING_SEASONS
    from .hls_fields import (
        Site,
        choose_dates,
        coverage,
        interior_pixels,
        read_parcels,
        read_windows,
    )
else:
    from .config import PROC, RAW, REPO, SOWING_LAT, SOWING_LON, SOWING_SEASONS
    from .hls_fields import Site, choose_dates, coverage, interior_pixels, read_parcels, read_windows

API = "https://planetarycomputer.microsoft.com/api"
BANDS = ("B03", "B04", "B05", "Fmask")
BATCH_LABEL_COLUMNS = [
    "array_index",
    "field_id",
    "date_utc",
    "season",
    "granule",
    "candidate_clear_pixels",
    "candidate_pixels",
    "context_file",
    "full_interior_pixels",
    "clear_interior_pixels",
    "farm_id",
    "crop_id",
    "sown_on",
    "label",
    "evidence",
    "split",
]


def catalog(site, periods=SOWING_SEASONS):
    by_id = {}
    for start, end in periods:
        params = {
            "collections": "hls2-l30",
            "limit": 250,
            "intersects": json.dumps({"type": "Point", "coordinates": [site.lon, site.lat]}),
            "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        }
        url = f"{API}/stac/v1/search"
        while url:
            response = requests.get(url, params=params, timeout=45)
            response.raise_for_status()
            page = response.json()
            for feature in page["features"]:
                by_id[feature["id"]] = feature
            url = next((link["href"] for link in page["links"] if link["rel"] == "next"), None)
            params = None
    return sorted(by_id.values(), key=lambda f: f["id"])


def official_catalog(site, features, periods=SOWING_SEASONS):
    rows = []
    for start, end in periods:
        page = 1
        while True:
            params = {
                "short_name": "HLSL30",
                "version": "2.0",
                "point": f"{site.lon},{site.lat}",
                "page_size": 500,
                "page_num": page,
                "temporal": f"{start}T00:00:00Z,{end}T23:59:59Z",
            }
            response = requests.get(
                "https://cmr.earthdata.nasa.gov/search/granules.umm_json",
                params=params,
                timeout=(15, 60),
            )
            response.raise_for_status()
            result = response.json()
            rows.extend(
                (item["umm"]["GranuleUR"], item["meta"]["concept-id"]) for item in result["items"]
            )
            if page * params["page_size"] >= result["hits"]:
                break
            if len(result["items"]) != params["page_size"]:
                raise RuntimeError("Incomplete NASA catalog page")
            page += 1
    frame = (
        pd.DataFrame(rows, columns=["granule", "nasa_concept_id"])
        .drop_duplicates()
        .sort_values("granule")
    )
    nasa_ids = set(frame["granule"])
    mirror_ids = {feature["id"] for feature in features}
    nasa_only = sorted(nasa_ids - mirror_ids)
    mirror_only = sorted(mirror_ids - nasa_ids)

    # A mirror-only granule has no official NASA provenance: fail closed.
    if mirror_only:
        raise RuntimeError(
            f"{len(mirror_only)} HLS granule(s) exist in the mirror but cannot "
            f"be verified in NASA CMR; refusing to download: "
            f"{mirror_only[:10]}"
        )

    # A NASA-only granule cannot be downloaded by this mirror-based pipeline.
    # Report the gap, but process all granules verified in BOTH catalogs.
    if nasa_only:
        print(
            f"WARNING: {len(nasa_only)} NASA HLS granule(s) are absent "
            "from the Planetary Computer mirror and will NOT be downloaded:",
            flush=True,
        )
        for granule_id in nasa_only:
            print(f"  NASA-only: {granule_id}", flush=True)
        print(
            f"Proceeding with {len(nasa_ids & mirror_ids)} cross-verified "
            "granule(s). Coverage is incomplete relative to NASA CMR.",
            flush=True,
        )

    return frame[frame["granule"].isin(mirror_ids)].copy()


def storage(href):
    url = urlsplit(href)
    return url.hostname.split(".")[0], url.path.split("/")[1]


def online_features(site, periods):
    features = catalog(site, periods)
    ids = official_catalog(site, features, periods).set_index("granule")["nasa_concept_id"]
    for f in features:
        f["nasa_concept_id"] = ids[f["id"]]
    return features


def cached_features(site, periods):
    """Read signed-URL-free acquisition metadata from old manifests or new raw-clip tags."""
    legacy = {}
    batches = PROC / "evia_sowing" / "hls_batches"
    sources = [site.directory(PROC)]
    if batches.is_dir():
        sources.extend(
            p / site.name / "hls"
            for p in batches.iterdir()
            if p.is_dir() and not p.name.endswith(".partial")
        )
    for folder in sources:
        manifest, nasa = folder / "acquisitions.csv", folder / "nasa_catalog.csv"
        if manifest.is_file() and nasa.is_file():
            records = pd.read_csv(manifest).merge(
                pd.read_csv(nasa), on="granule", validate="one_to_one"
            )
            legacy.update(records.set_index("granule").to_dict("index"))
    features = []
    for path in sorted(site.directory(RAW).glob("HLS.L30.*.v2.0.tif")):
        scene = path.stem
        # The day is also present in the HLS granule ID, including in pre-existing clips.
        day = datetime.strptime(scene.split(".")[3][:7], "%Y%j").date().isoformat()
        if not any(start <= day <= end for start, end in periods):
            continue
        row = legacy.get(scene)
        if row is None:
            row = checked_clip(path, site)
        if not row.get("acquired_utc") or not row.get("nasa_concept_id"):
            raise ValueError(f"Missing catalog metadata for cached {scene}. Run the online batch.")
        features.append(
            {
                "id": scene,
                "nasa_concept_id": row["nasa_concept_id"],
                "properties": {
                    "datetime": row["acquired_utc"],
                    "platform": row.get("platform", ""),
                },
            }
        )
    return features


def checked_clip(path, site):
    with rasterio.open(path) as ds:
        x, y = transform("EPSG:4326", ds.crs, [site.lon], [site.lat])
        if (
            ds.descriptions != BANDS
            or ds.shape != (site.size, site.size)
            or ds.index(x[0], y[0]) != (site.size // 2, site.size // 2)
        ):
            raise ValueError(
                f"Cached clip for {site.name} has a different window or bands. Use a new field_id."
            )
        return ds.tags()


def install_new(tmp, target):
    """Publish a complete cache file only if another process has not already created it."""
    try:
        if os.name == "nt":
            tmp.rename(target)
        else:
            os.link(tmp, target)
        return True
    except FileExistsError:
        return False


def claim_window(site):
    folder = site.directory(RAW)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "window.json"
    window = {"longitude": site.lon, "latitude": site.lat, "size": site.size}
    if not path.is_file():
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=folder, prefix=".window-", delete=False
        ) as handle:
            tmp = Path(handle.name)
            json.dump(window, handle)
        try:
            install_new(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
    if json.loads(path.read_text(encoding="utf-8")) != window:
        raise ValueError(
            f"Raw cache for {site.name} belongs to another centre or size. Use a new field_id."
        )


def write_clip(feature, site, grid, bands):
    scene = feature["id"]
    target = site.directory(RAW) / f"{scene}.tif"
    with NamedTemporaryFile(
        dir=target.parent, prefix=".hls-", suffix=".tif", delete=False
    ) as handle:
        tmp = Path(handle.name)
    try:
        with rasterio.open(
            tmp,
            "w",
            driver="GTiff",
            count=4,
            dtype="int16",
            width=site.size,
            height=site.size,
            crs=grid[0],
            transform=grid[1],
            compress="deflate",
        ) as ds:
            ds.write(np.stack(bands))
            ds.descriptions = BANDS
            ds.update_tags(
                granule=scene,
                acquired_utc=feature["properties"]["datetime"],
                platform=feature["properties"].get("platform") or "",
                nasa_concept_id=feature["nasa_concept_id"],
                scale_B03_B04_B05="0.0001",
                fill_reflectance="-9999",
                fill_Fmask="255",
            )
        if not install_new(tmp, target):
            checked_clip(target, site)
    finally:
        tmp.unlink(missing_ok=True)


def download_scene(feature, sites, tokens):
    """Open each remote band once for all missing crops of this granule."""
    for attempt in range(3):
        try:
            arrays = {site: [] for site in sites}
            grids = {}
            with rasterio.Env(
                GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                CURL_CA_BUNDLE=certifi.where(),
                GDAL_HTTP_CONNECTTIMEOUT="15",
                GDAL_HTTP_TIMEOUT="45",
                GDAL_HTTP_MAX_RETRY="2",
                GDAL_HTTP_RETRY_DELAY="1",
                CPL_LOG="NUL",
            ):
                for name in BANDS:
                    href = feature["assets"][name]["href"].split("?")[0]
                    with rasterio.open(href + "?" + tokens[storage(href)]) as src:
                        if not np.allclose(src.res, (30, 30)):
                            raise ValueError("Expected a native 30 m raster")
                        fill = 255 if name == "Fmask" else -9999
                        by_window = {}
                        xs, ys = transform(
                            "EPSG:4326", src.crs, [s.lon for s in sites], [s.lat for s in sites]
                        )
                        for site, x, y in zip(sites, xs, ys):
                            row, col = src.index(x, y)
                            win = Window(
                                col - site.size // 2, row - site.size // 2, site.size, site.size
                            )
                            grid = (src.crs, src.window_transform(win))
                            if grids.setdefault(site, grid) != grid:
                                raise ValueError("HLS band grids differ")
                            if win not in by_window:
                                by_window[win] = src.read(
                                    1, window=win, boundless=True, fill_value=fill
                                ).astype("int16")
                            arrays[site].append(by_window[win])
            for site in sites:
                write_clip(feature, site, grids[site], arrays[site])
            return
        except (rasterio.errors.RasterioIOError, requests.RequestException) as err:
            if attempt == 2:
                # Signed storage query strings must never be written to logs.
                raise RuntimeError(
                    f"Failed to read the windows for {feature['id']} ({type(err).__name__})"
                ) from None
            time.sleep(2**attempt)


def fetch_missing(by_site, workers, cached_only):
    jobs = {}
    for site, features in by_site.items():
        folder = site.directory(RAW)
        if (folder / "window.json").is_file():
            claim_window(site)
        existing = next(folder.glob("HLS.L30.*.v2.0.tif"), None)
        if existing:
            checked_clip(existing, site)
        pending = []
        for f in features:
            target = folder / (f["id"] + ".tif")
            if target.is_file():
                checked_clip(target, site)
            else:
                if cached_only:
                    raise ValueError(f"Missing cached clip {target}")
                pending.append(f)
        if pending:
            claim_window(site)
            for f in pending:
                jobs.setdefault(f["id"], (f, []))[1].append(site)
    if not jobs:
        print("All selected field windows are already cached.", flush=True)
        return
    containers = {storage(f["assets"][band]["href"]) for f, _ in jobs.values() for band in BANDS}
    tokens = {}
    for account, container in containers:
        response = requests.get(f"{API}/sas/v1/token/{account}/{container}", timeout=35)
        response.raise_for_status()
        tokens[account, container] = response.json()["token"].lstrip("?")

    def download(job):
        feature, sites = job
        download_scene(feature, sites, tokens)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, _ in enumerate(pool.map(download, jobs.values()), 1):
            if i % 10 == 0 or i == len(jobs):
                print(f"Cached windows for {i}/{len(jobs)} distinct source granules", flush=True)


def save_catalog(features, out):
    pd.DataFrame(
        [(f["id"], f["nasa_concept_id"]) for f in features], columns=["granule", "nasa_concept_id"]
    ).sort_values("granule").to_csv(out / "nasa_catalog.csv", index=False)


def collect_fields(
    fields_csv,
    *,
    size=33,
    max_dates=18,
    workers=5,
    parcels=None,
    cached_only=False,
    plan_only=False,
):
    """Download selected windows and return a new training batch directory, or preview its plan."""
    if not 1 <= workers <= 8 or (max_dates is not None and max_dates < 1):
        raise ValueError("Use 1-8 workers and a positive max_dates, or None for all dates")
    requests_by_site = read_windows(Path(fields_csv), size)
    geometries = read_parcels(Path(parcels)) if parcels is not None else {}
    if parcels is not None:
        missing = {s.name for s in requests_by_site} - geometries.keys()
        if missing:
            raise ValueError(f"Missing confirmed polygons for: {', '.join(sorted(missing))}")
    source = "local_cache" if cached_only else "NASA_CMR_and_mirror"
    by_site, selections = {}, {}
    for site, windows in requests_by_site.items():
        periods = [(w.start, w.end) for w in windows]
        features = cached_features(site, periods) if cached_only else online_features(site, periods)
        all_days = {f["properties"]["datetime"][:10] for f in features}
        keep = set()
        for w in windows:
            available = {d for d in all_days if w.start <= d <= w.end}
            days = choose_dates(available, max_dates)
            selections[w] = (len(available), days)
            keep.update(days)
            print(
                f"{site.name} {w.start} to {w.end}: {len(days)}/{len(available)} UTC dates selected ({source})",
                flush=True,
            )
        by_site[site] = [f for f in features if f["properties"]["datetime"][:10] in keep]
    unique = {f["id"] for features in by_site.values() for f in features}
    print(
        f"{len(by_site)} field(s), {len(unique)} distinct source granules across the batch.",
        flush=True,
    )
    if plan_only:
        return None
    fetch_missing(by_site, workers, cached_only)

    # New snapshots preserve older context_file references, pilot data and human label sheets.
    parent = PROC / "evia_sowing" / "hls_batches"
    parent.mkdir(parents=True, exist_ok=True)
    final = parent / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    stage = final.with_name(final.name + ".partial")
    stage.mkdir()
    summaries, sheets = [], []
    try:
        for site, windows in requests_by_site.items():
            features = by_site[site]
            if features:
                out = stage / site.name / "hls"
                out.mkdir(parents=True)
                labels = prepare(
                    features, site, out, final / site.name / "hls", geometries.get(site.name)
                )
                save_catalog(features, out)
            else:
                labels = pd.DataFrame(
                    columns=["date_utc", "clear_interior_pixels", "full_interior_pixels"]
                )
            for w in windows:
                available, days = selections[w]
                rows = labels[labels.date_utc.isin(days)].copy()
                row = coverage(w, available, days, rows, bool(geometries), source)
                row["context_file"] = labels["context_file"].iloc[0] if features else ""
                summaries.append(row)
                if not rows.empty:
                    rows["farm_id"], rows["crop_id"], rows["sown_on"] = (
                        w.farm_id,
                        w.crop_id,
                        w.sown_on,
                    )
                    sheets.append(rows)
        summary = pd.DataFrame(summaries)
        summary.to_csv(stage / "field_coverage.csv", index=False)
        labels = (
            pd.concat(sheets, ignore_index=True)
            if sheets
            else pd.DataFrame(columns=BATCH_LABEL_COLUMNS)
        )
        labels.to_csv(stage / "labels_template.csv", columns=BATCH_LABEL_COLUMNS, index=False)
        stage.rename(final)
    finally:
        # The only scratch directory removed here was created by this call inside the batch root.
        if (
            stage.exists()
            and stage.resolve().parent == parent.resolve()
            and stage.name.endswith(".partial")
        ):
            shutil.rmtree(stage)
    print(
        summary[
            ["field_id", "start_date", "selected_dates", "usable_dates", "days_short_of_six"]
        ].to_string(index=False)
    )
    print(f"Batch saved to {final}", flush=True)
    return final


def aligned_clip_array(dataset, target_grid):
    """Read an HLS native clip on one reference grid, preserving QA and nodata.

    HLS source tiles can have different affine origins (or even CRSs). A stack
    of window arrays from those tiles is NOT a geospatially aligned time series.
    Nearest-neighbour reprojection keeps exact Fmask bits and avoids creating
    synthetic reflectance values by interpolation. Any out-of-footprint pixels
    remain nodata and are excluded by the usual clear-pixel check.
    """
    target_crs, target_transform = target_grid
    current_grid = (dataset.crs.to_string(), tuple(dataset.transform)[:6])
    if current_grid == target_grid:
        return dataset.read()

    destination = np.empty((len(BANDS), dataset.height, dataset.width), dtype="int16")
    for index, band_name in enumerate(BANDS):
        nodata = 255 if band_name == "Fmask" else -9999
        destination[index].fill(nodata)
        reproject(
            source=rasterio.band(dataset, index + 1),
            destination=destination[index],
            src_transform=dataset.transform,
            src_crs=dataset.crs,
            src_nodata=nodata,
            dst_transform=rasterio.Affine(*target_transform),
            dst_crs=target_crs,
            dst_nodata=nodata,
            resampling=Resampling.nearest,
            init_dest_nodata=True,
        )
    return destination


def prepare(features, site, out=None, published_dir=None, geometry=None):
    out = site.directory(PROC) if out is None else out
    final = out if published_dir is None else published_dir
    roi = np.zeros((site.size, site.size), dtype=bool)
    centre = site.size // 2
    roi[centre - 1 : centre + 2, centre - 1 : centre + 2] = True
    rows, scenes = [], {}
    grid = None
    field = roi
    aligned_count = 0
    for f in features:
        scene = f["id"]
        with rasterio.open(site.directory(RAW) / f"{scene}.tif") as ds:
            if ds.descriptions != BANDS or ds.shape != (site.size, site.size):
                raise ValueError(f"Unexpected clip layout: {scene}")
            current = (ds.crs.to_string(), tuple(ds.transform)[:6])
            if grid is None:
                # Keep the first source scene's native 30 m grid as the
                # batch reference; record its CRS and transform in the NPZ.
                grid = current
                if geometry is not None:
                    field = interior_pixels(grid[0], grid[1], ds.shape, geometry)
            needs_alignment = current != grid
            raw = aligned_clip_array(ds, grid)
            if needs_alignment:
                aligned_count += 1
        qa = raw[3].astype("uint8")
        # Fmask bits 1–5 = cloud, adjacent cloud, shadow, snow/ice, water.
        # A conservative extra filter excludes high aerosol (bits 6–7 both set).
        clear = (qa != 255) & ((qa & 62) == 0) & ((qa >> 6) != 3) & (raw[:3] != -9999).all(axis=0)
        reflectance = raw[:3].astype("float32") * np.float32(0.0001)
        reflectance[:, ~clear] = np.nan
        scenes[scene] = (reflectance, qa, clear)
        properties = f["properties"]
        date = properties["datetime"][:10]
        year = int(date[:4]) if int(date[5:7]) >= 9 else int(date[:4]) - 1
        red, nir = reflectance[1], reflectance[2]
        valid_ndvi = roi & clear & ((nir + red) > 0)
        ndvi = (nir[valid_ndvi] - red[valid_ndvi]) / (nir[valid_ndvi] + red[valid_ndvi])
        row = {
            "date_utc": date,
            "acquired_utc": properties["datetime"],
            "season": f"{year}-{year+1}",
            "granule": scene,
            "native_grid_aligned": needs_alignment,
            "tile": scene.split(".")[2],
            "platform": properties.get("platform"),
            "candidate_clear_pixels": int((roi & clear).sum()),
            "candidate_pixels": int(roi.sum()),
            "context_clear_pixels": int(clear.sum()),
            "candidate_median_ndvi": float(np.median(ndvi)) if ndvi.size else np.nan,
            "source_stac": f"{API}/stac/v1/collections/hls2-l30/items/{scene}",
        }
        if published_dir is not None:
            row["full_interior_pixels"] = int(field.sum())
            row["clear_interior_pixels"] = int((field & clear).sum())
        rows.append(row)
    if aligned_count:
        print(
            f"HLS: aligned {aligned_count}/{len(features)} cached clips to "
            f"a common 30 m reference grid for {site.name}; "
            "native source clips remain unchanged.",
            flush=True,
        )
    quality_key = "candidate_clear_pixels" if published_dir is None else "clear_interior_pixels"
    manifest = (
        pd.DataFrame(rows)
        .sort_values(
            ["date_utc", quality_key, "context_clear_pixels", "granule"],
            ascending=[True, False, False, True],
        )
        .reset_index(drop=True)
    )
    manifest["selected"] = ~manifest.date_utc.duplicated()
    manifest["array_index"] = pd.Series(pd.NA, index=manifest.index, dtype="Int64")
    manifest.loc[manifest.selected, "array_index"] = np.arange(int(manifest.selected.sum()))
    chosen = manifest[manifest.selected]
    ids = chosen.granule.tolist()
    temp = out / "field_context.partial.npz"
    np.savez_compressed(
        temp,
        reflectance=np.stack([scenes[k][0] for k in ids]),
        fmask=np.stack([scenes[k][1] for k in ids]),
        clear=np.stack([scenes[k][2] for k in ids]),
        candidate_mask=roi,
        dates=chosen.date_utc.to_numpy(dtype="U10"),
        granules=np.array(ids),
        bands=np.array(BANDS[:3]),
        crs=grid[0],
        transform=grid[1],
        longitude=site.lon,
        latitude=site.lat,
    )
    temp.replace(out / "field_context.npz")
    manifest.to_csv(out / "acquisitions.csv", index=False, float_format="%.6f")
    labels = chosen[
        [
            "array_index",
            "date_utc",
            "season",
            "granule",
            "candidate_clear_pixels",
            "candidate_pixels",
        ]
    ].copy()
    labels.insert(1, "field_id", site.name)
    labels["context_file"] = (final / "field_context.npz").relative_to(REPO).as_posix()
    if published_dir is not None:
        labels[["full_interior_pixels", "clear_interior_pixels"]] = chosen[
            ["full_interior_pixels", "clear_interior_pixels"]
        ]
    for col in ("farm_id", "crop_id", "sown_on", "label", "evidence", "split"):
        labels[col] = ""
    if published_dir is None:
        labels.to_csv(out / "labels_template.csv", index=False)
        print(
            chosen.groupby("season")
            .agg(
                dates=("granule", "size"),
                full_clear=("candidate_clear_pixels", lambda x: (x == 9).sum()),
                some_clear=("candidate_clear_pixels", lambda x: (x > 0).sum()),
            )
            .to_string(),
            flush=True,
        )
    return labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=5, choices=range(1, 9))
    parser.add_argument("--site", help="Unique output name for a single field")
    parser.add_argument("--lon", type=float)
    parser.add_argument("--lat", type=float)
    parser.add_argument(
        "--size", type=int, default=33, help="Odd side length in native 30 m pixels"
    )
    parser.add_argument(
        "--fields", type=Path, help="CSV of field centres and inclusive date windows"
    )
    limit = parser.add_mutually_exclusive_group()
    limit.add_argument("--max-dates", type=int, help="Distinct dates per CSV row (default 18)")
    limit.add_argument(
        "--all-dates", action="store_true", help="Use every available date in each CSV window"
    )
    parser.add_argument(
        "--parcels", type=Path, help="Optional confirmed WGS84 polygons for the CSV fields"
    )
    parser.add_argument(
        "--cached-only", action="store_true", help="Use only local raw windows and catalog metadata"
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Report the date plan without writing files or downloading imagery",
    )
    args = parser.parse_args()
    try:
        if args.fields is not None:
            if any(v is not None for v in (args.site, args.lon, args.lat)):
                parser.error("Pass field centres through the CSV when using --fields")
            maximum = None if args.all_dates else (18 if args.max_dates is None else args.max_dates)
            collect_fields(
                args.fields,
                size=args.size,
                max_dates=maximum,
                workers=args.workers,
                parcels=args.parcels,
                cached_only=args.cached_only,
                plan_only=args.plan,
            )
            return
        if (
            args.max_dates is not None
            or args.all_dates
            or args.parcels
            or args.cached_only
            or args.plan
        ):
            parser.error("Use --fields for batch date, parcel, cache and planning options")
        site = Site(
            args.site or "evia_pilot",
            SOWING_LON if args.lon is None else args.lon,
            SOWING_LAT if args.lat is None else args.lat,
            args.size,
        )
        features = online_features(site, SOWING_SEASONS)
        if not features:
            raise ValueError("No HLSL30 granules found")
        fetch_missing({site: features}, args.workers, False)
        out = site.directory(PROC)
        out.mkdir(parents=True, exist_ok=True)
        prepare(features, site)
        save_catalog(features, out)
    except (ValueError, FileNotFoundError) as exc:
        parser.exit(2, f"HLS: {exc}\n")


if __name__ == "__main__":
    main()
