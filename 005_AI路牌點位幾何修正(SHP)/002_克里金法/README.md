# 路標坐標 Kriging 修正流程說明

## 概述

本流程以路面控制點的 dX、dY 偏移量，透過 Ordinary Kriging 內插建立修正網格，再套用至待修正點位，完成 AI 偵測路標的幾何修正。

共分兩支腳本執行：

| 腳本 | 功能 |
|------|------|
| `01_dXdY_Correction_Kriging_Grid.py` | 以控制點進行 Kriging，輸出 dX / dY 修正網格（GeoTIFF） |
| `02_CorrectPts_byKriging_Grid.py` | 讀取修正網格，對待修正點位套用修正量，輸出修正後 shp |

---

## 腳本一：`01_dXdY_Correction_Kriging_Grid.py`

### 功能說明

以控制點的 dX、dY 欄位分別建立 Ordinary Kriging 模型，在 ROI（路面範圍）內建立 1 公尺解析度的修正網格，並輸出 GeoTIFF。

### 輸入資料

| 參數 | 說明 |
|------|------|
| `ROI_V01_PairwiseDissolve.shp` | 路面範圍 polygon，用於定義網格範圍與遮罩 |
| `修正前_控制點_操作.shp` | 控制點，須包含 `dX`、`dY` 欄位（單位：公尺） |

### 關鍵參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `cell_size` | `1.0` | Raster 解析度（公尺） |
| `chunk_size` | `5000` | 每批處理像元數，記憶體不足可調小 |
| `n_closest_points` | `3` | 局部 Kriging 使用鄰近控制點數 |
| `nodata` | `-9999.0` | NoData 值 |

### 輸出資料

| 檔案 | 說明 |
|------|------|
| `dX_kriging_1m.tif` | dX 修正量網格（單 band） |
| `dY_kriging_1m.tif` | dY 修正量網格（單 band） |
| `dXdY_kriging_1m.tif` | 雙 band 合併版（Band 1 = dX，Band 2 = dY） |

### 執行注意事項

- 控制點與 ROI 須使用投影坐標系（建議 TWD97 TM2，EPSG:3826）
- 控制點 CRS 若與 ROI 不同，程式會自動重投影
- 只有落在 ROI 內（intersects）的控制點會參與 Kriging
- 至少需要 3 個不重複坐標的有效控制點
- Variogram 模型預設為 `spherical`，可依需求改為 `linear`、`gaussian` 等

---

## 腳本二：`02_CorrectPts_byKriging_Grid.py`

### 功能說明

逐點對待修正 shp 取得 Kriging 修正量，完成坐標修正並輸出結果。對 raster 範圍外或 NoData 的點，自動以 KDTree 找最近有效網格 cell 進行外插補正。

### 輸入資料

| 參數 | 說明 |
|------|------|
| `待修正.shp` | 待修正點位（AI 偵測路標） |
| `dX_kriging_1m.tif` | 腳本一輸出的 dX 修正網格 |
| `dY_kriging_1m.tif` | 腳本一輸出的 dY 修正網格 |

### 輸出資料

| 檔案 | 說明 |
|------|------|
| `SIGN_0527_修正後_raster_nearest.shp` | 修正後點位 shp，含 dX_k、dY_k、corr_type、near_dist 等欄位 |
| `SIGN_外插最近網格清單.txt` | 使用最近網格（非直接 raster 取樣）的點位清單，供人工複查 |

### 輸出 shp 欄位說明

| 欄位 | 說明 |
|------|------|
| `X_ori` / `Y_ori` | 修正前坐標 |
| `X_new` / `Y_new` | 修正後坐標 |
| `dX_k` / `dY_k` | 套用的 Kriging 修正量（公尺） |
| `corr_type` | `raster`：直接取樣；`nearest`：最近網格外插 |
| `near_dist` | 外插時與最近有效 cell 的距離（`raster` 類型為 0） |
| `near_x` / `near_y` | 實際取樣 cell 中心坐標 |
| `near_row` / `near_col` | 實際取樣 cell 的 raster 行列索引 |

### 修正公式

```
X_new = X_ori + dX_k
Y_new = Y_ori + dY_k
```

> 若實測後方向相反，改為減號（腳本內已有註解說明）。

### 執行注意事項

- 程式不自動對 raster 進行 CRS 轉換，待修正點位的坐標系需與 raster 一致
- 若 raster 標示為 LOCAL_CS 但實質為 EPSG:3826，直接執行即可，無需調整
- 輸出 txt 清單中列出的點位，需人工判斷外插修正是否合理

---

## 執行環境需求

```
geopandas
rasterio
numpy
pandas
pykrige
scipy
shapely
```

安裝指令：

```bash
pip install geopandas rasterio numpy pandas pykrige scipy shapely
```

---

## 建議執行順序

1. 準備 ROI shp 與控制點 shp，確認欄位 `dX`、`dY` 已填寫正確
2. 設定腳本一路徑參數，執行 `01_dXdY_Correction_Kriging_Grid.py`
3. 確認三個 GeoTIFF 輸出正常（可在 QGIS 開啟檢查 Kriging 結果）
4. 設定腳本二路徑參數，執行 `02_CorrectPts_byKriging_Grid.py`
5. 確認輸出 shp 與 txt，對 `corr_type = nearest` 的點位進行人工複查
