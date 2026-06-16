from osgeo import gdal, osr

ph = r"97221068dem.tif"
ds = gdal.Open(ph)
gt = ds.GetGeoTransform()
band = ds.GetRasterBand(1)

cols = ds.RasterXSize
rows = ds.RasterYSize

# ── GeoTransform ──────────────────────────────────────
print("=" * 45)
print("▌ GeoTransform")
print(f"  左上角 X (edge) : {gt[0]}")
print(f"  左上角 Y (edge) : {gt[3]}")
print(f"  像素寬度 (X)    : {gt[1]}")
print(f"  像素高度 (Y)    : {gt[5]}")
print(f"  旋轉 X          : {gt[2]}")
print(f"  旋轉 Y          : {gt[4]}")
print(f"  影像大小        : {cols} 欄 × {rows} 列")

# ── 四角範圍 ──────────────────────────────────────────
left   = gt[0]
top    = gt[3]
right  = gt[0] + gt[1] * cols
bottom = gt[3] + gt[5] * rows

print("\n▌ 範圍（pixel edge 為準）")
print(f"  左 X  : {left}")
print(f"  右 X  : {right}")
print(f"  上 Y  : {top}")
print(f"  下 Y  : {bottom}")
print(f"  寬度  : {right - left} 公尺")
print(f"  高度  : {top - bottom} 公尺")

# ── 像素對齊推斷 ──────────────────────────────────────
ps = gt[1]  # 像素大小

# 若座標是像素大小的整數倍 → pixel edge
# 若座標是像素大小的半整數倍 → pixel center
def guess_alignment(coord, pixel_size):
    remainder = coord % pixel_size
    half = pixel_size / 2
    if abs(remainder) < 1e-6 or abs(remainder - pixel_size) < 1e-6:
        return "pixel edge"
    elif abs(remainder - half) < 1e-6:
        return "pixel center"
    else:
        return f"不明（餘數 {remainder:.4f}）"

align = guess_alignment(gt[0], ps)


print("\n▌ 像素對齊推斷")
print(f"  像素對齊 : {align}")

# 換算成另一種表示
cx = gt[0] + ps * 0.5
cy = gt[3] + gt[5] * 0.5

if align == "pixel edge":
    print(f"\n  為 pixel edge  → 左上像素 center = ({cx}, {cy})")
elif align == "pixel center":
    print(f"  為 pixel center                  = ({gt[0]}, {gt[3]})")
    print(f"  為 pixel center → 左上 edge       = ({gt[0] - ps * 0.5}, {gt[3] - gt[5] * 0.5})")


# ── 投影座標系 ────────────────────────────────────────
srs = osr.SpatialReference()
srs.ImportFromWkt(ds.GetProjection())

print("\n▌ 投影座標系")
print(f"  名稱   : {srs.GetName()}")

# 類型
if srs.IsProjected():
    print(f"  類型   : 投影座標系 (Projected)")
    print(f"  單位   : {srs.GetLinearUnitsName()}")
elif srs.IsGeographic():
    print(f"  類型   : 地理座標系 (Geographic)")
    print(f"  單位   : {srs.GetAngularUnitsName()}")

# ── NoData ────────────────────────────────────────────
nodata = band.GetNoDataValue()
print("\n▌ NoData")
print(f"  值     : {nodata if nodata is not None else '未定義'}")

# ── 資料型態 ──────────────────────────────────────────
dtype_map = {
    1: "Byte (uint8)", 2: "UInt16", 3: "Int16", 4: "UInt32",
    5: "Int32", 6: "Float32", 7: "Float64"
}
print("\n▌ 資料型態")
print(f"  Band 1 : {dtype_map.get(band.DataType, band.DataType)}")

print("=" * 45)

ds = None