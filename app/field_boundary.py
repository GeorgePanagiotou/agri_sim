"""Field boundaries, local imagery and point-in-time parcel evidence."""
import base64
import io
import json

import numpy as np
import pandas as pd
import rasterio
import streamlit as st
import xarray as xr
from PIL import Image
from affine import Affine
from rasterio.warp import transform_geom
from shapely.errors import ShapelyError
from shapely.geometry import shape, mapping, box
from shapely.affinity import affine_transform

from agrisim.config import PROC, OUTPUTS, STUDY_AREA
from agrisim.data_sources.hls_fields import interior_pixels
from agrisim.data_sources.field_hls import field_hls_plan, candidate_archives
from agrisim.decision_engine.fusion import fuse
from agrisim.decision_engine.vegetation_history import apply_greenup, SOURCE
from agrisim.timeseries.greenup import COLUMNS_REQUIRED, quality_dates
from agrisim.timeseries.vegetation_indices import stats
from field_profiles import save_input

SUPPORT = "user_drawn_or_uploaded_boundary"
MAP = PROC / "imagery/landsat_rgb_2025-06-10_landsat-9.tif"
DRAW = st.components.v2.component("evia_boundary", html="""
<svg viewBox="0 0 541 754" style="height:480px;max-width:100%;cursor:crosshair;display:block">
<image width="541" height="754"/><path fill="#20bd6b55" stroke="#fff" stroke-width="2" fill-rule="evenodd"/>
<polygon fill="#ffba3066" stroke="#ffc637" stroke-width="2"/></svg>
<button>Undo vertex</button> <button>Save drawn boundary</button><span></span>
""", js="""
export default function({parentElement:p,data,setTriggerValue}){
 const svg=p.querySelector('svg'), poly=p.querySelector('polygon'), buttons=p.querySelectorAll('button');
 const pts=svg._points ||= [];
 svg.querySelector('image').setAttribute('href',data.image);
 svg.querySelector('path').setAttribute('d',data.path);
 function refresh(){poly.setAttribute('points',pts.map(v=>v.join(',')).join(' '));buttons[1].disabled=pts.length<3;p.querySelector('span').textContent=' '+pts.length+' vertices';}
 svg.onclick=e=>{const v=new DOMPoint(e.clientX,e.clientY).matrixTransform(svg.getScreenCTM().inverse());pts.push([v.x,v.y]);refresh();};
 buttons[0].onclick=()=>{pts.pop();refresh();};
 buttons[1].onclick=()=>{setTriggerValue('vertices',pts.map(v=>[...v]));pts.length=0;refresh();};
 refresh();
}
""")


def validate(obj):
    if not isinstance(obj, dict):
        raise ValueError("Expected a GeoJSON polygon.")
    if obj.get("type") == "FeatureCollection":
        if len(obj.get("features", [])) != 1:
            raise ValueError("Upload exactly one field feature.")
        obj = obj["features"][0]
    if obj.get("type") == "Feature":
        obj = obj.get("geometry")
    if not isinstance(obj,dict) or obj.get("type") not in ("Polygon","MultiPolygon"):
        raise ValueError("Upload a Polygon or MultiPolygon geometry.")
    g = shape(obj)
    if g.geom_type not in ("Polygon","MultiPolygon") or g.is_empty or not g.is_valid:
        raise ValueError("Use a valid Polygon or MultiPolygon without crossing edges.")
    w,e,s,n = STUDY_AREA
    if not box(w,s,e,n).covers(g):
        raise ValueError("The boundary must be within the North Evia study area (WGS84 longitude/latitude).")
    return json.dumps(mapping(g),allow_nan=False)


@st.cache_data
def basemap():
    with rasterio.open(MAP) as ds:
        buf=io.BytesIO()
        Image.fromarray(ds.read().transpose(1,2,0)).save(buf,format="JPEG")
        return "data:image/jpeg;base64,"+base64.b64encode(buf.getvalue()).decode(), ds.transform, ds.crs.to_string()


def boundary_editor(field, saved):
    with st.expander("Field boundary",expanded=False):
        st.caption("Saved for this field." if saved else "This field has no saved boundary.")
        mode=st.radio("Boundary input",["Upload GeoJSON","Draw on imagery"],horizontal=True,key=f"mode_{field}")
        try:
            obj=None
            if mode=="Upload GeoJSON":
                upload=st.file_uploader("WGS84 Polygon or MultiPolygon",type=["json","geojson"],key=f"upload_{field}")
                if upload and st.button("Save uploaded boundary",key=f"upload_save_{field}"):
                    obj=json.loads(upload.getvalue())
            else:
                image,tr,crs=basemap()
                path=""
                if saved:
                    g=affine_transform(shape(transform_geom("EPSG:4326",crs,json.loads(saved))),(~tr).to_shapely())
                    for polygon in (g.geoms if g.geom_type=="MultiPolygon" else [g]):
                        for ring in [polygon.exterior,*polygon.interiors]:
                            path+="M"+" L".join(f"{x},{y}" for x,y in ring.coords)+" Z "
                st.caption("Click around the field on the 10 June 2025 Landsat image. White outlines show the saved boundary.")
                event=DRAW(data=dict(image=image,path=path),key=f"draw_{field}",on_vertices_change=lambda: None)
                if event.vertices:
                    ring=[tr*tuple(p) for p in event.vertices]
                    obj=transform_geom(crs,"EPSG:4326",dict(type="Polygon",coordinates=[ring+[ring[0]]]))
            if obj is not None:
                boundary=validate(obj)
                save_input(field,"boundary",boundary)
                st.rerun()
        except (ValueError,TypeError,AttributeError,KeyError,IndexError,ShapelyError) as exc:
            st.error(f"Boundary could not be saved. {exc}")


@st.cache_data(show_spinner=False)
def parcel_series(field,boundary,archive,revision):
    with np.load(archive,allow_pickle=False) as z:
        try:
            mask=interior_pixels(str(z["crs"].item()),tuple(z["transform"]),z["candidate_mask"].shape,json.loads(boundary))
        except ValueError as exc:
            return pd.DataFrame(), str(exc)
        if mask.sum()<4:
            return pd.DataFrame(), "Fewer than four complete 30 m HLS pixels fit inside the field."
        records=pd.read_csv(archive.with_name("acquisitions.csv"))
        times=pd.to_datetime(records.available_utc,utc=True,format="mixed").groupby(records.date_utc)
        available=times.max().where(times.count().eq(times.size()))
        rows=[]
        for index,(day,granule,arr,clear) in enumerate(zip(z['dates'],z['granules'],z['reflectance'],z['clear'])):
            source = str(z['sources'][index]) if 'sources' in z.files else SOURCE
            row=stats(str(field),str(day),source,SUPPORT,*arr,clear,mask,granule=str(granule))
            row['available_utc']=available.get(str(day))
            rows.append(row)
    return pd.DataFrame(rows), f"{mask.sum()} complete 30 m HLS pixels inside this boundary."


@st.cache_data(show_spinner=False)
def annual_cover(boundary,year,revision):
    with xr.open_dataset(PROC/"landsat_field_years.nc") as ds:
        geom=json.loads(boundary)
        g=shape(transform_geom("EPSG:4326",ds.attrs['crs'],geom))
        w,s,e,n=g.bounds
        sub=ds.sel(x=slice(w-30,e+30),y=slice(n+30,s-30))
        if year not in ds.year or not len(sub.x) or not len(sub.y):
            return None
        tr=Affine(30,0,float(sub.x[0])-15,0,-30,float(sub.y[0])+15)
        try:
            mask=interior_pixels(ds.attrs['crs'],tuple(tr)[:6],(len(sub.y),len(sub.x)),geom)
        except ValueError:
            return None
        codes=sub.year_class.sel(year=year).values[mask]
        counts=[(codes==i).sum() for i in (1,2,3)]
        if not sum(counts):
            return None
        return ", ".join(f"{name} {count/sum(counts):.0%}" for name,count in zip(["crop","fallow/low","summer crop"],counts) if count) + f" ({sum(counts)}/{len(codes)} classified pixels)"


def field_assessment(r,field,boundary):
    # Prefer the field's own complete-coverage archive; never assume that the
    # newest 33×33 evia_pilot clip contains the selected saved polygon.
    obs=pd.DataFrame(columns=sorted(COLUMNS_REQUIRED|{"spatial_support","available_utc"}))
    status="No saved boundary. Field satellite evidence is unavailable."
    if boundary:
        try:
            site_name=field_hls_plan(boundary,field).site.name
        except ValueError:
            # Oversized polygons still get checked against pre-existing imagery.
            site_name=f"field_{field}_unavailable"
        checked=0
        status="Local HLS imagery is unavailable for this saved boundary."
        for path in candidate_archives(PROC,site_name):
            manifest=path.with_name("acquisitions.csv")
            if not manifest.is_file():
                continue
            checked+=1
            sampled, explanation=parcel_series(
                field,boundary,path,(path.stat().st_mtime_ns,manifest.stat().st_mtime_ns))
            if not sampled.empty:
                obs=sampled
                status=explanation+f" Archive: {path.parent.parent.name}."
                break
            status=explanation
        if checked and obs.empty and status.startswith("Parcel extends"):
            status += " Acquire a versioned field-specific HLS window below."
    base=fuse(pd.read_csv(OUTPUTS/"sowing_weeks.csv").query("week_start == @r.week_start"),
              pd.read_csv(OUTPUTS/"risk_daily.csv"),season=r.season,crop_id=r.crop_id)
    result=apply_greenup(base,obs,field_id=str(field),support=SUPPORT).iloc[0]
    updated=r.copy()
    for col in result.index:
        if col.startswith(("greenup_","vegetation_")) or col in ("decision_explanation","recommended_action","week_vs_latest_prior_greenup","component_a_vegetation_status"):
            updated[col]=result[col]
    if updated.decision_priority=="candidate_for_field_check" and pd.notna(updated.rotation_options):
        updated.recommended_action+=" Confirm the preceding crop for these rotation phases: "+updated.rotation_options+"."
    annual=PROC/"landsat_field_years.nc"
    cover=annual_cover(boundary,int(r.rotation_prior_season_end_year),annual.stat().st_mtime_ns) if boundary and annual.exists() else None
    updated.rotation_prior_landsat_class=cover
    if cover:
        note=f" Previous field cover: {cover}. Confirm crop identity from field records."
        updated.decision_explanation+=note
        if updated.decision_priority=="candidate_for_field_check":
            updated.recommended_action+=note
    updated["field_profile_id"]=field
    updated["field_satellite_coverage"]=status
    visible=obs[pd.to_datetime(obs.available_utc,utc=True)<pd.Timestamp(r.week_start,tz="UTC")]
    return updated,status,quality_dates(visible)


def render_field_hls_acquisition(field, boundary, assessment_week, coverage):
    """Expose a deliberate, user-triggered network acquisition when coverage fails."""
    if not boundary:
        return
    needs_archive = coverage.startswith((
        "Parcel extends beyond the archive", "Local HLS imagery is unavailable",
    ))
    with st.expander("Acquire or refresh field HLS imagery", expanded=needs_archive):
        if not needs_archive:
            st.caption("The existing archive covers this polygon. Refresh it here to collect later "
                       "acquisition dates for the selected season.")
        st.caption("Acquisition is field-specific; the original Evia pilot archive is left unchanged. "
                   "Uses NASA-verified HLSL30 and optionally HLSS30 scenes, preserving availability timestamps.")
        include_s30 = st.checkbox("Include Sentinel-2 S30 (narrow NIR B8A)", value=False,
                                  key=f"include_s30_{field}")
        try:
            plan=field_hls_plan(boundary,field)
        except ValueError as exc:
            st.error(str(exc))
            st.warning("Check the field polygon first. Downloading a partial HLS window "
                       "would produce misleading field vegetation evidence.")
            return
        st.write(f"Polygon area: {plan.area_hectares:,.1f} ha · "
                 f"needed window: {plan.site.size}×{plan.site.size} native 30 m pixels")
        st.caption("All available HLSL30 dates per September–May season across four seasons. "
                   "Clouds, Landsat revisit and catalog gaps can reduce usable observations.")
        st.caption("All available dates can involve many granules and large downloads. "
                   "S30 acquisition is opt-in; remote S30 delivery has not yet been live-tested.")
        if st.button("Download field-specific HLS imagery", key=f"hls_fetch_{field}_{plan.boundary_digest[:12]}"):
            from agrisim.data_sources.download_evia_hls import collect_saved_boundary
            try:
                with st.spinner("Retrieving and preparing verified HLS scenes…"):
                    batch=collect_saved_boundary(boundary,field,as_of=str(assessment_week),
                                                 seasons=4,max_dates=None,workers=3,
                                                 include_s30=include_s30)
                parcel_series.clear()
                st.success(f"Field imagery saved in {batch}. Updating assessment.")
                st.rerun()
            except Exception as exc:
                # Keep errors visible in the app rather than hiding partial coverage.
                st.error(f"HLS acquisition did not complete: {type(exc).__name__}: {exc}")
