# Limitations

- One provisional 90 m region and 12 previously usable HLS dates cannot support a validated general-purpose crop emergence ML system.
- NDVI/EVI2 greening may indicate weeds, perennial plants, or surrounding vegetation rather than the sown crop.
- Repeated images of the same field are correlated; random image splits cause leakage.
- HLS (30 m) and Sentinel-2 (10–20 m) must be co-registered with correct native masks and scale factors before joint analysis.
- PELT and Savitzky–Golay are retrospective tools. Interpolated dates are not real satellite measurements.
- The simple bucket model lacks calibration, runoff/drainage detail and direct field measurements.
- No crop-rotation yield or calibrated risk-probability model has been trained.
- FAO GAEZ layers can only be applied with a documented scenario, crop, input regime and legend.
