# shp點資料用DEM取z值.py

## 功能概述

從多幅 DEM（GeoTIFF）中，批次萃取 SHP 點位的高程值（Z），並寫入新的 Shapefile。

---

## 流程說明

```
讀取 Excel 圖框範圍
    ↓
建立虛擬矩形圖框（GeoDataFrame）
    ↓
讀取點位 SHP
    ↓
Spatial Join（點位 × 圖框）→ 找出每個點所屬圖幅
    ↓
依圖幅分群，逐一開啟對應 DEM（rasterio）
    ↓
萃取像素高程值，寫入 pts_gdf[Z]
    ↓
另存新 SHP
```

---

## 參數設定

| 參數 | 說明 |
|------|------|
| `dem_folder` | DEM GeoTIFF 所在資料夾 |
| `excel_path` | 含圖框範圍的 Excel 檔路徑 |
| `sheet_name` | 工作表名稱 |
| `shp_input_path` | 輸入點位 SHP 路徑 |
| `shp_output_path` | 輸出 SHP 路徑 |
| `z_field_name` | 寫入高程的欄位名稱（預設 `"Z"`） |

---

## 依賴套件

- `pandas`
- `geopandas`
- `shapely`
- `rasterio`

---

## 注意事項

- Excel 標題列預設在第 3 列（`header=2`），請依實際狀況調整。
- DEM 檔名格式須為 `{圖幅_5K}dem.tif`（例如：`97221dem.tif`）。
- 找不到對應 DEM 的點位，Z 值保留為 `-9999`。
- 圖框 CRS 會自動對齊點位 SHP 的 CRS（`allow_override=True`）。
