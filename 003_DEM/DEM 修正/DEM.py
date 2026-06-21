import os
import pandas as pd
import numpy as np
from osgeo import gdal
from tqdm import tqdm
from contextlib import contextmanager

# ==================== 1. 參數設定 ====================
input_dir = r"DEM 修正"  # 原始 DEM 修正 路徑
output_dir = r"成果"  # 成果儲存路徑
excel_path = r"電子地圖正射圖幅外擴計算表.xlsx"  # 座標 Excel
max_search_dist = 1  # 搜尋鄰近像素的距離，針對 1 像素空洞設為 1

# ==================== 2. 準備工作 ====================
os.makedirs(output_dir, exist_ok=True)  # 省去 if not exists
# 先單獨讀取完整的 Excel 分頁，用來抓取儲存格 B3 的動態解析度
df_raw = pd.read_excel(excel_path, sheet_name="121正射用圖框", header=None)
# Excel 的 B3 儲存格，在沒有標頭(header=None)的點陣矩陣中，對應索引為 [列2, 欄1]
resolution = float(df_raw.iloc[2, 1])
print(f"➔ 偵測到 Excel 規劃解析度：{resolution} 公尺")

# 保持原有邏輯：從第 3 列 (header=2) 開始讀取正式欄位資料
df = pd.read_excel(excel_path, header=2, sheet_name="121正射用圖框")
df = df.dropna(subset=['圖幅_5K'])
df['圖幅_5K'] = df['圖幅_5K'].astype(float).astype(int).astype(str)
# ==================== 3. 核心處理迴圈 ====================
def process_tile(row: pd.Series, input_dir: str, output_dir: str,
                 resolution: float, max_search_dist: int) -> str | None:
    """
    處理單一圖幅，回傳錯誤訊息或 None（成功）。
    所有 GDAL Dataset 用區域變數管理，函式結束自動釋放。
    """
    map_id  = row['圖幅_5K']
    in_path = os.path.join(input_dir,  f"{map_id}dem.tif")
    out_path = os.path.join(output_dir, f"{map_id}dem.tif")

    if not os.path.exists(in_path):
        return f"{map_id}: 找不到原始檔案"

    try:
        # Step A: 讀入並建立記憶體副本
        src_ds = gdal.Open(in_path, gdal.GA_ReadOnly)
        if src_ds is None:
            return f"{map_id}: GDAL 無法開啟檔案"

        mem_ds = gdal.GetDriverByName('MEM').CreateCopy('', src_ds)
        src_ds = None  # 盡早釋放原始檔案鎖定

        band = mem_ds.GetRasterBand(1)
        nodata_val = band.GetNoDataValue() or -99999
        band.SetNoDataValue(nodata_val)

        # Step B: 極端值遮罩
        data = band.ReadAsArray().astype(np.float32)
        data[(data > 4000) | (data < -100)] = nodata_val
        band.WriteArray(data)
        del data  # 釋放大陣列記憶體

        # Step C: 補洞
        gdal.FillNodata(targetBand=band, maskBand=None,
                        maxSearchDist=max_search_dist, smoothingIterations=0)

        # Step D: 裁切對齊
        proj_win = [row['左X2'], row['上Y2'], row['右X2'], row['下Y2']]
        trans_ds = gdal.Translate('', mem_ds, format='MEM',
                                  projWin=proj_win, resampleAlg='near')
        mem_ds = None

        if trans_ds is None:
            return f"{map_id}: gdal.Translate 失敗"

        # Step E: 實心化（合併兩個條件，減少陣列掃描次數）
        out_band  = trans_ds.GetRasterBand(1)
        final_data = out_band.ReadAsArray().astype(np.float32)
        nd = out_band.GetNoDataValue()
        invalid = np.isnan(final_data)
        if nd is not None:
            invalid |= (final_data == nd)
        final_data[invalid] = 0

        # Step F: 寫出 GeoTIFF
        driver = gdal.GetDriverByName('GTiff')
        dst_ds = driver.Create(out_path,
                               trans_ds.RasterXSize, trans_ds.RasterYSize,
                               1, gdal.GDT_Float32,
                               ['COMPRESS=DEFLATE', 'TILED=YES'])  # 加壓縮省空間
        dst_ds.SetProjection(trans_ds.GetProjection())
        dst_ds.SetGeoTransform((row['左X'], resolution, 0.0,
                                row['上Y'], 0.0, -resolution))
        dst_band = dst_ds.GetRasterBand(1)
        dst_band.WriteArray(final_data)
        dst_band.DeleteNoDataValue()
        dst_ds.FlushCache()  # 確保寫入完畢再離開

        return None  # 成功

    except Exception as e:
        return f"{map_id}: 處理異常 — {e}"


# ==================== 4. 主迴圈 ====================
error_list = []
for _, row in tqdm(df.iterrows(), total=len(df), desc="產製進度", unit="幅"):
    err = process_tile(row, input_dir, output_dir, resolution, max_search_dist)
    if err:
        error_list.append(err)

# ==================== 5. 統計報告 ====================
success = len(df) - len(error_list)
print(f"\n{'='*40}\n作業完成！ 成功：{success} | 異常：{len(error_list)}")
if error_list:
    log_path = os.path.join(output_dir, "處理異常清單.txt")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(error_list))
    print(f"詳細錯誤清單請見: {log_path}")
print("="*40)
