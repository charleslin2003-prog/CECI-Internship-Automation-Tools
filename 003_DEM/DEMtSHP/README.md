# shp點資料用DEM取z值.py

## 一、功能概述

從多幅 DEM（GeoTIFF）中，批次萃取 SHP 點位的高程值（Z），並寫入新的 Shapefile。透過 Excel 圖框範圍建立虛擬圖層，以空間連接判斷各點所屬圖幅，再逐幅取樣。

---

## 二、依賴套件

| 套件 | 用途 |
|------|------|
| `pandas` | 讀取 Excel 圖框 |
| `geopandas` | SHP 讀寫、空間連接（sjoin） |
| `shapely` | `box` 建立矩形圖框幾何 |
| `rasterio` | 開啟 DEM、`sample` 取樣高程 |

---

## 三、處理流程

```
讀取 Excel 圖框範圍（工作表：121正射用圖框，header=2）
    ↓
以四角點 X/Y 之 min/max 建立虛擬矩形圖框（box）→ GeoDataFrame
    ↓
讀取點位 SHP，CRS 對齊圖框
    ↓
Spatial Join（點位 × 圖框，predicate="intersects"）→ 找出每點所屬圖幅
    ↓
依「圖幅_5K」分群，逐一開啟對應 DEM（每幅只開一次）
    ↓
rasterio.sample 萃取像素高程，寫入 pts_gdf[Z]
    ↓
另存新 SHP
```

---

## 四、參數設定

| 參數 | 說明 |
|------|------|
| `dem_folder` | DEM GeoTIFF 所在資料夾 |
| `excel_path` | 含圖框範圍的 Excel 檔路徑 |
| `sheet_name` | 工作表名稱（`"121正射用圖框"`） |
| `shp_input_path` | 輸入點位 SHP 路徑 |
| `shp_output_path` | 輸出 SHP 路徑 |
| `z_field_name` | 寫入高程的欄位名稱（預設 `"Z"`） |

---

## 五、Excel 欄位需求

工作表標題列在第 3 列（`header=2`），須含 `圖幅_5K` 與八個頂點座標欄位：`X1,Y1,X2,Y2,X3,Y3,X4,Y4`。

---

## 六、注意事項

- DEM 檔名格式須為 `{圖幅_5K}dem.tif`（例如 `97221dem.tif`）。
- 圖框 CRS 自動對齊點位 SHP 的 CRS（`set_crs(..., allow_override=True)`）。
- Z 欄位初始化為 `-9999.0`；取到 NoData 或找不到對應 DEM 的點，Z 保留 `-9999`。
- 點位依所屬圖幅分群處理，每個 DEM 檔只開啟一次以提升效率。
- 輸出另存為新 SHP（`encoding='utf-8'`），不覆蓋原始檔。