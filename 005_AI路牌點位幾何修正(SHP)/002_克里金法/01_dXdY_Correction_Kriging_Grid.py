# -*- coding: utf-8 -*-
"""
功能：
1. 讀取路面範圍 ROI_V01_PairwiseDissolve.shp
2. 讀取控制點 修正前_控制點_操作.shp
3. 使用控制點欄位 dX、dY 分別進行 Ordinary Kriging
4. 以 ROI 範圍建立 1m raster
5. raster 只保留 ROI polygon 內部
6. 輸出：
   - dX_kriging_1m.tif
   - dY_kriging_1m.tif
   - dXdY_kriging_1m.tif  # 兩個 band，Band 1=dX, Band 2=dY

注意：
- dX、dY 單位應與坐標單位一致，通常為公尺
- ROI 與點位資料建議使用投影坐標，例如 TWD97 TM2
"""

import os
import math
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.transform import from_origin
from rasterio.features import rasterize
from pykrige.ok import OrdinaryKriging


# =========================================================
# 1. 路徑設定
# =========================================================

roi_path = r"ROI_V01_PairwiseDissolve.shp"

point_path = r"修正前_控制點_操作.shp"

out_dir = r""

out_dx_tif = os.path.join(out_dir, "dX_kriging_1m.tif")
out_dy_tif = os.path.join(out_dir, "dY_kriging_1m.tif")
out_2band_tif = os.path.join(out_dir, "dXdY_kriging_1m.tif")

# raster 解析度，單位為坐標單位，這裡是 1 公尺
cell_size = 1.0

# NoData 值
nodata = -9999.0

# Kriging 每次處理多少個 raster cell
# 若電腦記憶體不足，可以調小，例如 2000
chunk_size = 5000

# 局部克利金使用鄰近點數
# 建議不要用全域所有點，避免局部異常或 variogram 不穩
n_closest_points = 3


# =========================================================
# 2. 讀取資料
# =========================================================

roi_gdf = gpd.read_file(roi_path)
pt_gdf = gpd.read_file(point_path)

# CRS 檢查
if roi_gdf.crs is None:
    raise ValueError("ROI shp 沒有 CRS，請先定義投影坐標系。")

if pt_gdf.crs is None:
    raise ValueError("控制點 shp 沒有 CRS，請先定義投影坐標系。")

if roi_gdf.crs != pt_gdf.crs:
    pt_gdf = pt_gdf.to_crs(roi_gdf.crs)

# 合併 ROI geometry，相容新舊 geopandas
try:
    roi_union = roi_gdf.geometry.union_all()
except AttributeError:
    roi_union = roi_gdf.geometry.unary_union


# =========================================================
# 3. 檢查控制點欄位
# =========================================================

need_fields = ["dX", "dY"]

for f in need_fields:
    if f not in pt_gdf.columns:
        raise ValueError(f"控制點 shp 缺少欄位：{f}")

pt_gdf["dX"] = pd.to_numeric(pt_gdf["dX"], errors="coerce")
pt_gdf["dY"] = pd.to_numeric(pt_gdf["dY"], errors="coerce")

pt_gdf = pt_gdf.dropna(subset=["dX", "dY"]).copy()

# 只取落在 ROI 內或碰到 ROI 的控制點
# 如果你希望 ROI 外附近控制點也參與克利金，可以註解掉這行
pt_gdf = pt_gdf[pt_gdf.geometry.intersects(roi_union)].copy()

if len(pt_gdf) < 3:
    raise ValueError("有效控制點少於 3 點，無法進行克利金內插。")

pt_gdf["X"] = pt_gdf.geometry.x
pt_gdf["Y"] = pt_gdf.geometry.y

# 移除重複坐標
pt_gdf = pt_gdf.drop_duplicates(subset=["X", "Y"]).copy()

if len(pt_gdf) < 3:
    raise ValueError("移除重複坐標後，控制點少於 3 點。")

print("控制點數量：", len(pt_gdf))
print("dX 統計：")
print(pt_gdf["dX"].describe())
print("dY 統計：")
print(pt_gdf["dY"].describe())


# =========================================================
# 4. 建立 1m raster 範圍
# =========================================================

minx, miny, maxx, maxy = roi_gdf.total_bounds

# 讓 raster 邊界對齊整數公尺
left = math.floor(minx / cell_size) * cell_size
bottom = math.floor(miny / cell_size) * cell_size
right = math.ceil(maxx / cell_size) * cell_size
top = math.ceil(maxy / cell_size) * cell_size

width = int(round((right - left) / cell_size))
height = int(round((top - bottom) / cell_size))

transform = from_origin(left, top, cell_size, cell_size)

print("Raster 範圍：")
print("left, bottom, right, top =", left, bottom, right, top)
print("width, height =", width, height)
print("總像元數 =", width * height)


# =========================================================
# 5. 建立 ROI mask
# =========================================================

roi_mask = rasterize(
    [(geom, 1) for geom in roi_gdf.geometry if geom is not None and not geom.is_empty],
    out_shape=(height, width),
    transform=transform,
    fill=0,
    dtype="uint8",
    all_touched=True
)

inside_rows, inside_cols = np.where(roi_mask == 1)

inside_count = len(inside_rows)
print("ROI 內像元數：", inside_count)

if inside_count == 0:
    raise ValueError("ROI rasterize 後沒有任何有效像元，請檢查 ROI 範圍或 CRS。")


# =========================================================
# 6. 計算 ROI 內像元中心坐標
# =========================================================

# col → x center
x_cells = left + (inside_cols + 0.5) * cell_size

# row → y center
y_cells = top - (inside_rows + 0.5) * cell_size


# =========================================================
# 7. 建立 Kriging 模型
# =========================================================

x = pt_gdf["X"].to_numpy()
y = pt_gdf["Y"].to_numpy()
dx = pt_gdf["dX"].to_numpy()
dy = pt_gdf["dY"].to_numpy()

print("建立 dX Ordinary Kriging 模型...")
OK_dx = OrdinaryKriging(
    x,
    y,
    dx,
    variogram_model="spherical",
    verbose=False,
    enable_plotting=False
)

print("建立 dY Ordinary Kriging 模型...")
OK_dy = OrdinaryKriging(
    x,
    y,
    dy,
    variogram_model="spherical",
    verbose=False,
    enable_plotting=False
)


# =========================================================
# 8. 分批對 ROI 內像元做 Kriging
# =========================================================

dx_raster = np.full((height, width), nodata, dtype="float32")
dy_raster = np.full((height, width), nodata, dtype="float32")

total = inside_count

print("開始 Kriging 內插 raster...")

for start in range(0, total, chunk_size):
    end = min(start + chunk_size, total)

    xs = x_cells[start:end]
    ys = y_cells[start:end]

    rows = inside_rows[start:end]
    cols = inside_cols[start:end]

    print(f"處理像元 {start + 1} ~ {end} / {total}")

    # dX
    dx_pred, dx_var = OK_dx.execute(
        "points",
        xs,
        ys,
        n_closest_points=n_closest_points,
        backend="loop"
    )

    # dY
    dy_pred, dy_var = OK_dy.execute(
        "points",
        xs,
        ys,
        n_closest_points=n_closest_points,
        backend="loop"
    )

    dx_raster[rows, cols] = np.asarray(dx_pred, dtype="float32")
    dy_raster[rows, cols] = np.asarray(dy_pred, dtype="float32")


# =========================================================
# 9. 輸出 GeoTIFF
# =========================================================

os.makedirs(out_dir, exist_ok=True)

profile = {
    "driver": "GTiff",
    "height": height,
    "width": width,
    "count": 1,
    "dtype": "float32",
    "crs": roi_gdf.crs,
    "transform": transform,
    "nodata": nodata,
    "compress": "lzw"
}

# dX 單 band
with rasterio.open(out_dx_tif, "w", **profile) as dst:
    dst.write(dx_raster, 1)
    dst.set_band_description(1, "dX_kriging")

# dY 單 band
with rasterio.open(out_dy_tif, "w", **profile) as dst:
    dst.write(dy_raster, 1)
    dst.set_band_description(1, "dY_kriging")

# 兩 band 合併版
profile_2band = profile.copy()
profile_2band["count"] = 2

with rasterio.open(out_2band_tif, "w", **profile_2band) as dst:
    dst.write(dx_raster, 1)
    dst.write(dy_raster, 2)
    dst.set_band_description(1, "dX_kriging")
    dst.set_band_description(2, "dY_kriging")

print("完成輸出：")
print(out_dx_tif)
print(out_dy_tif)
print(out_2band_tif)