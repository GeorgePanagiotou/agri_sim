# Methodology and caveats

1. Download a specific approved product and retain the product identifier, acquisition timestamp, native units, grid and quality metadata.
2. Apply product-specific cloud/quality masking **before** NDVI/EVI2 calculation. Extract field polygon interiors when verified.
3. Keep imagery acquisition dates separate from interpolated/smoothed daily dates. A gap may only bound a green-up interval, not the exact emergence day.
4. Use Savitzky–Golay and (optionally) PELT `ruptures` to propose vegetation changes; check transition direction and actual clear observations before accepting. BFAST is not implemented.
5. For a candidate sowing week, join only daily inputs that were available **before** that week. NASA POWER / GPM / SMAP data are regional.
6. Compare farmer-entered rotations under the same weather/initial assumptions; report qualitative score and uncertain water-budget estimates separately from independently observed yields.
7. Train ML only on farmer-observed or field-verified outcome records and group the split by farm. Never evaluate satellite pseudo-labels as independently verified ground truth.
