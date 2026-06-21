import os
import pandas as pd
import geopandas as gpd
from shapely.geometry import box
import rasterio

# ==========================================
# --- 1. 參數設定區 ---
# ==========================================
dem_folder = r"成果"
excel_path = r"電子地圖正射圖幅外擴計算表.xlsx"  # 你的 Excel 檔案路徑
sheet_name = "121正射用圖框"  # 你要讀取的工作表名稱
shp_input_path = r"faketienoz.shp"  # 原始點位 SHP 檔路徑
shp_output_path = r"faketienoz_V1.shp"  # 處理完後另存的新 SHP 檔
z_field_name = "Z"  # 寫入高程的欄位名稱

# ==========================================
# --- 2. 讀取 Excel 並建立虛擬圖框圖層 ---
# ==========================================
print("1. 正在讀取 Excel 圖框範圍...")
# 根據你的 CSV 截圖，標題列似乎在第 2 或第 3 列，請根據實際狀況調整 header 參數 (0-based)
# 假設標題列在第 3 列 (index 2)
df_grid = pd.read_excel(excel_path, sheet_name=sheet_name, header=2)

# 改為檢查原圖框的 8 個頂點座標欄位是否存在/無空值
coord_cols = ['X1', 'Y1', 'X2', 'Y2', 'X3', 'Y3', 'X4', 'Y4']
df_grid = df_grid.dropna(subset=['圖幅_5K'] + coord_cols)
df_grid['圖幅_5K'] = df_grid['圖幅_5K'].astype(int).astype(str)

# 動態抓取四個角點中 X 與 Y 的最大/最小值，並建立矩形範圍
df_grid['geometry'] = df_grid.apply(
    lambda row: box(
        min(row['X1'], row['X2'], row['X3'], row['X4']),  # 左 (X_min)
        min(row['Y1'], row['Y2'], row['Y3'], row['Y4']),  # 下 (Y_min)
        max(row['X1'], row['X2'], row['X3'], row['X4']),  # 右 (X_max)
        max(row['Y1'], row['Y2'], row['Y3'], row['Y4'])   # 上 (Y_max)
    ),
    axis=1
)

# 轉換為 GeoDataFrame
grid_gdf = gpd.GeoDataFrame(df_grid, geometry='geometry')

# ==========================================
# --- 3. 讀取 SHP 並進行空間連接 (Spatial Join) ---
# ==========================================
print("2. 載入 SHP 點位並執行空間交集分析...")
pts_gdf = gpd.read_file(shp_input_path)

# 確保圖框的座標系統 (CRS) 與點位 SHP 檔一致，才能進行精確交集
grid_gdf.set_crs(pts_gdf.crs, inplace=True, allow_override=True)

# 執行 Spatial Join：把點位落在哪個圖框的資訊，直接貼到點位屬性表後面
# 這一步完美取代了 arcpy.analysis.SpatialJoin
joined_gdf = gpd.sjoin(pts_gdf, grid_gdf, how="left", predicate="intersects")

# 初始化 Z 欄位，預設給 -9999
pts_gdf[z_field_name] = -9999.0

# ==========================================
# --- 4. 批次萃取 DEM 高程 (Rasterio) ---
# ==========================================
print("\n3. 開始提取高程...")
# 將點位依照所屬的「圖幅_5K」進行分群，這樣每個 DEM 檔只要打開一次就好
grouped = joined_gdf.groupby('圖幅_5K')

for mapid, group in grouped:
    dem_path = os.path.join(dem_folder, f"{mapid}dem.tif")

    if not os.path.exists(dem_path):
        print(f"⚠️ 找不到 DEM：{dem_path}")
        continue

    print(f"👉 處理圖幅 {mapid} (包含 {len(group)} 個點位)...")

    # 取出這群點位的 X, Y 座標對
    coords = [(geom.x, geom.y) for geom in group.geometry]

    # 使用 Rasterio 開啟 DEM 並提取數值
    try:
        with rasterio.open(dem_path) as src:
            # src.sample 會返回一個產生器，裡面包含這些座標對應的像素值
            extracted_vals = [val[0] for val in src.sample(coords)]
            nodata_val = src.nodata  # 取得該影像定義的 NoData 值

            # 將提取到的高程寫回原本的 pts_gdf
            for i, idx in enumerate(group.index):
                val = extracted_vals[i]
                # 確保抓到的不是 NoData，才寫入真實數值
                if val != nodata_val and not pd.isna(val):
                    pts_gdf.at[idx, z_field_name] = float(val)
    except Exception as e:
        print(f"讀取圖幅 {mapid} 時發生錯誤: {e}")

# ==========================================
# --- 5. 匯出處理結果 ---
# ==========================================
print("\n4. 寫入完成，正在儲存新的 SHP 檔...")
# 將結果另存為新的 Shapefile (可避免覆蓋或弄壞原始檔案)
pts_gdf.to_file(shp_output_path, encoding='utf-8')

print(f"🎉 處理完成！結果已儲存至：{shp_output_path}")