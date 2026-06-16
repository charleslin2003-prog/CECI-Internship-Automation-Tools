# -*- coding: utf-8 -*-
"""
功能：
1. 讀取待修正點 SIGN_0527.shp
2. 讀取 dX_kriging_1m.tif、dY_kriging_1m.tif
3. 點位若落在有效 raster cell 內，直接使用該 cell 的 dX / dY 修正
4. 點位若落在 raster 外或 NoData，找最近的有效修正網格 cell 進行外插修正
5. 輸出修正後 shp
6. 輸出外插點 txt 清單，提醒使用者留意

修正公式：
    X_new = X_ori + dX_k
    Y_new = Y_ori + dY_k

若方向相反，請改成：
    X_new = X_ori - dX_k
    Y_new = Y_ori - dY_k
"""

import os
import numpy as np
import geopandas as gpd
import rasterio
from shapely.geometry import Point
from scipy.spatial import cKDTree


# =========================================================
# 1. 路徑設定
# =========================================================

point_path = r"待修正.shp"

dx_raster_path = r"dX_kriging_1m.tif"
dy_raster_path = r"dY_kriging_1m.tif"

out_point_path = r"SIGN_0527_修正後_raster_nearest.shp"

out_txt_path = r"SIGN_外插最近網格清單.txt"


# =========================================================
# 2. 小工具
# =========================================================

def is_nodata(value, nodata):
    """判斷 raster 值是否為 NoData"""
    if value is None:
        return True
    if np.isnan(value):
        return True
    if nodata is not None and np.isclose(value, nodata):
        return True
    return False


def get_cell_center(transform, row, col):
    """由 row, col 取得 raster cell 中心坐標"""
    x, y = rasterio.transform.xy(transform, row, col, offset="center")
    return float(x), float(y)


# =========================================================
# 3. 讀取待修正點
# =========================================================

pt_gdf = gpd.read_file(point_path)

if pt_gdf.crs is None:
    raise ValueError("待修正點 shp 沒有 CRS，請先定義投影坐標系。")

pt_gdf = pt_gdf.reset_index(drop=True).copy()
pt_gdf["pt_id"] = pt_gdf.index

pt_gdf["X_ori"] = pt_gdf.geometry.x
pt_gdf["Y_ori"] = pt_gdf.geometry.y


# =========================================================
# 4. 讀取 raster
# =========================================================

with rasterio.open(dx_raster_path) as dx_src, rasterio.open(dy_raster_path) as dy_src:

    # -----------------------------------------------------
    # raster 基本檢查
    # -----------------------------------------------------
    if dx_src.transform != dy_src.transform:
        raise ValueError("dX raster 與 dY raster 的 transform 不一致。")

    if dx_src.width != dy_src.width or dx_src.height != dy_src.height:
        raise ValueError("dX raster 與 dY raster 的尺寸不一致。")

    print("dX raster CRS：", dx_src.crs)
    print("dY raster CRS：", dy_src.crs)
    print("待修正點 CRS：", pt_gdf.crs)

    # 因你的 raster 可能是 LOCAL_CS，但實際上與 EPSG:3826 相同
    # 這裡不做 CRS 轉換，直接使用原始 XY 取樣
    print("不執行 CRS 轉換，直接使用點位原始 XY 對 raster 取樣。")

    dx_arr = dx_src.read(1)
    dy_arr = dy_src.read(1)

    dx_nodata = dx_src.nodata
    dy_nodata = dy_src.nodata

    transform = dx_src.transform
    height = dx_src.height
    width = dx_src.width

    # -----------------------------------------------------
    # 建立有效修正網格 mask
    # 兩個 raster 都必須不是 NoData 才算有效
    # -----------------------------------------------------
    valid_mask = np.ones(dx_arr.shape, dtype=bool)

    if dx_nodata is not None:
        valid_mask &= ~np.isclose(dx_arr, dx_nodata)
    valid_mask &= ~np.isnan(dx_arr)

    if dy_nodata is not None:
        valid_mask &= ~np.isclose(dy_arr, dy_nodata)
    valid_mask &= ~np.isnan(dy_arr)

    valid_rows, valid_cols = np.where(valid_mask)

    if len(valid_rows) == 0:
        raise ValueError("dX / dY raster 沒有任何有效修正網格。")

    print("有效修正網格數：", len(valid_rows))

    # -----------------------------------------------------
    # 建立有效網格中心點 KDTree
    # 用來處理 raster 外或 NoData 點
    # -----------------------------------------------------
    print("建立最近有效修正網格索引 KDTree...")

    valid_xs = []
    valid_ys = []

    for r, c in zip(valid_rows, valid_cols):
        x, y = get_cell_center(transform, r, c)
        valid_xs.append(x)
        valid_ys.append(y)

    valid_xs = np.asarray(valid_xs)
    valid_ys = np.asarray(valid_ys)

    valid_xy = np.column_stack([valid_xs, valid_ys])
    tree = cKDTree(valid_xy)

    # -----------------------------------------------------
    # 逐點取得 dX / dY
    # -----------------------------------------------------
    dx_list = []
    dy_list = []
    corr_type_list = []
    near_dist_list = []
    near_x_list = []
    near_y_list = []
    near_row_list = []
    near_col_list = []

    extrapolate_records = []

    for idx, row in pt_gdf.iterrows():

        x = row["X_ori"]
        y = row["Y_ori"]

        use_nearest = False

        # 由坐標取得 raster row / col
        try:
            r, c = dx_src.index(x, y)
        except Exception:
            use_nearest = True
            r, c = None, None

        # -------------------------------------------------
        # 情況 A：點落在 raster 範圍內
        # -------------------------------------------------
        if not use_nearest and (0 <= r < height) and (0 <= c < width):

            dx_val = float(dx_arr[r, c])
            dy_val = float(dy_arr[r, c])

            # 如果該 cell 有效，直接使用
            if not is_nodata(dx_val, dx_nodata) and not is_nodata(dy_val, dy_nodata):
                dx_list.append(dx_val)
                dy_list.append(dy_val)
                corr_type_list.append("raster")
                near_dist_list.append(0.0)

                cell_x, cell_y = get_cell_center(transform, r, c)
                near_x_list.append(cell_x)
                near_y_list.append(cell_y)
                near_row_list.append(r)
                near_col_list.append(c)

                continue

            else:
                # raster 範圍內但剛好是 NoData
                use_nearest = True

        else:
            # raster 範圍外
            use_nearest = True

        # -------------------------------------------------
        # 情況 B：raster 外或 NoData，找最近有效 cell
        # -------------------------------------------------
        if use_nearest:

            dist, nearest_i = tree.query([x, y], k=1)

            nearest_r = int(valid_rows[nearest_i])
            nearest_c = int(valid_cols[nearest_i])

            dx_val = float(dx_arr[nearest_r, nearest_c])
            dy_val = float(dy_arr[nearest_r, nearest_c])

            near_x = float(valid_xs[nearest_i])
            near_y = float(valid_ys[nearest_i])

            dx_list.append(dx_val)
            dy_list.append(dy_val)
            corr_type_list.append("nearest")
            near_dist_list.append(float(dist))
            near_x_list.append(near_x)
            near_y_list.append(near_y)
            near_row_list.append(nearest_r)
            near_col_list.append(nearest_c)

            extrapolate_records.append({
                "pt_id": int(row["pt_id"]),
                "X_ori": x,
                "Y_ori": y,
                "near_x": near_x,
                "near_y": near_y,
                "near_row": nearest_r,
                "near_col": nearest_c,
                "dX_k": dx_val,
                "dY_k": dy_val,
                "near_dist": float(dist)
            })


# =========================================================
# 5. 寫入修正量欄位
# =========================================================

pt_gdf["dX_k"] = dx_list
pt_gdf["dY_k"] = dy_list
pt_gdf["corr_type"] = corr_type_list
pt_gdf["near_dist"] = near_dist_list
pt_gdf["near_x"] = near_x_list
pt_gdf["near_y"] = near_y_list
pt_gdf["near_row"] = near_row_list
pt_gdf["near_col"] = near_col_list

print(f"總點數：{len(pt_gdf)}")
print(f"直接使用 raster 修正：{sum(pt_gdf['corr_type'] == 'raster')}")
print(f"使用最近有效網格修正：{sum(pt_gdf['corr_type'] == 'nearest')}")


# =========================================================
# 6. 計算修正後坐標
# =========================================================

# 目前採用：原坐標 + 修正量
pt_gdf["X_new"] = pt_gdf["X_ori"] + pt_gdf["dX_k"]
pt_gdf["Y_new"] = pt_gdf["Y_ori"] + pt_gdf["dY_k"]

# 如果你的修正方向相反，改成下面兩行：
# pt_gdf["X_new"] = pt_gdf["X_ori"] - pt_gdf["dX_k"]
# pt_gdf["Y_new"] = pt_gdf["Y_ori"] - pt_gdf["dY_k"]


# =========================================================
# 7. 更新 geometry
# =========================================================

pt_gdf["geometry"] = [
    Point(xy) for xy in zip(pt_gdf["X_new"], pt_gdf["Y_new"])
]

out_gdf = gpd.GeoDataFrame(
    pt_gdf,
    geometry="geometry",
    crs=pt_gdf.crs
)


# =========================================================
# 8. 輸出修正後 shp
# =========================================================

out_dir = os.path.dirname(out_point_path)
os.makedirs(out_dir, exist_ok=True)

out_gdf.to_file(out_point_path, encoding="utf-8")

print("已輸出修正後點位：")
print(out_point_path)


# =========================================================
# 9. 輸出使用最近網格修正的點位清單
# =========================================================

with open(out_txt_path, "w", encoding="utf-8") as f:
    f.write("SIGN_0527 使用最近有效修正網格之點位清單\n")
    f.write("=" * 100 + "\n")
    f.write("說明：以下點位未直接取得有效 raster 修正量，可能位於 raster 範圍外或 ROI NoData 區。\n")
    f.write("程式已改用最近的有效 1m 修正網格 cell 之 dX / dY 進行移位。\n")
    f.write("使用者應特別檢查這些點位是否合理。\n")
    f.write("=" * 100 + "\n\n")

    if len(extrapolate_records) == 0:
        f.write("沒有使用最近網格修正的點位，所有點均直接套用 raster 修正量。\n")
    else:
        f.write(f"使用最近網格修正點數：{len(extrapolate_records)}\n\n")
        f.write("pt_id,X_ori,Y_ori,near_x,near_y,near_row,near_col,dX_k,dY_k,near_dist\n")

        for rec in extrapolate_records:
            f.write(
                f"{rec['pt_id']},"
                f"{rec['X_ori']:.4f},"
                f"{rec['Y_ori']:.4f},"
                f"{rec['near_x']:.4f},"
                f"{rec['near_y']:.4f},"
                f"{rec['near_row']},"
                f"{rec['near_col']},"
                f"{rec['dX_k']:.6f},"
                f"{rec['dY_k']:.6f},"
                f"{rec['near_dist']:.4f}\n"
            )

print("已輸出最近網格修正清單：")
print(out_txt_path)

print("全部完成。")