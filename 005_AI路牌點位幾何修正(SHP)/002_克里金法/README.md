# 克里金法改正（01 → 02）

> 本資料夾含兩支腳本，**依序執行**：先以腳本一建立修正網格，再以腳本二套用至待修正點位。

| 順序 | 腳本 | 功能 |
|------|------|------|
| ① | `01_dXdY_Correction_Kriging_Grid.py` | 以控制點 dX/dY 做 Ordinary Kriging，輸出 1m 修正網格 GeoTIFF |
| ② | `02_CorrectPts_byKriging_Grid.py` | 讀取修正網格，逐點套用修正，輸出修正後 SHP |

---

## 一、共同依賴套件

```bash
pip install geopandas rasterio numpy pandas pykrige scipy shapely
```

| 套件 | 用途 |
|------|------|
| `geopandas` / `shapely` | SHP 讀寫、ROI 幾何處理 |
| `rasterio` | raster 建立、遮罩、取樣、輸出 |
| `pykrige` | Ordinary Kriging 內插 |
| `scipy` | `cKDTree` 最近有效網格搜尋（腳本二） |
| `numpy` / `pandas` | 數值與統計 |

---

## 二、腳本一：`01_dXdY_Correction_Kriging_Grid.py`

### 功能

以控制點 `dX`、`dY` 欄位分別建立 Ordinary Kriging 模型，在 ROI（路面範圍）內建立 1m 解析度修正網格，輸出 GeoTIFF。

### 輸入

| 參數 | 說明 |
|------|------|
| `roi_path` | 路面範圍 polygon（定義網格範圍與遮罩） |
| `point_path` | 控制點 SHP，須含 `dX`、`dY` 欄位（單位：公尺） |

### 關鍵參數

| 參數 | 預設 | 說明 |
|------|------|------|
| `cell_size` | `1.0` | Raster 解析度（公尺） |
| `chunk_size` | `5000` | 每批處理像元數，記憶體不足可調小 |
| `n_closest_points` | `3` | 局部 Kriging 使用的鄰近控制點數 |
| `nodata` | `-9999.0` | NoData 值 |
| `variogram_model` | `"spherical"` | 半變異元模型，可改 linear / gaussian 等 |

### 處理流程

```
讀取 ROI 與控制點（CRS 檢查與重投影）
    ↓
篩選有效控制點（dX/dY 轉數值、去 NaN、去重複座標、僅取 intersects ROI）
    ↓
依 ROI total_bounds 建立對齊整數公尺的 1m raster 範圍
    ↓
rasterize ROI → mask（all_touched=True），只保留範圍內像元
    ↓
建立 dX、dY 兩個 OrdinaryKriging 模型
    ↓
分批（chunk）對 ROI 內像元中心做 Kriging（n_closest_points，backend="loop"）
    ↓
輸出 GeoTIFF（LZW 壓縮）
```

### 輸出

| 檔案 | 說明 |
|------|------|
| `dX_kriging_1m.tif` | dX 修正量網格（單 band） |
| `dY_kriging_1m.tif` | dY 修正量網格（單 band） |
| `dXdY_kriging_1m.tif` | 雙 band 合併版（Band 1 = dX，Band 2 = dY） |

### 注意事項

- 控制點與 ROI 須使用投影座標系（建議 TWD97 TM2 / EPSG:3826）；CRS 不同時程式自動重投影控制點。
- 僅落在 ROI 內（intersects）的控制點參與 Kriging。
- 去重後至少需 3 個有效控制點，否則拋錯。

---

## 三、腳本二：`02_CorrectPts_byKriging_Grid.py`

### 功能

逐點對待修正 SHP 取得 Kriging 修正量並完成座標修正。落在 raster 範圍外或 NoData 的點，以 `cKDTree` 找最近有效網格 cell 進行外插補正。

### 輸入

| 參數 | 說明 |
|------|------|
| `point_path` | 待修正點位（AI 偵測路標） |
| `dx_raster_path` | 腳本一輸出的 dX 修正網格 |
| `dy_raster_path` | 腳本一輸出的 dY 修正網格 |

### 處理流程

```
讀取待修正點（須有 CRS）
    ↓
讀取 dX / dY raster，檢查 transform 與尺寸一致
    ↓
建立有效修正網格 mask（兩 raster 皆非 NoData / NaN）
    ↓
有效網格中心建立 cKDTree
    ↓
逐點：
  ├─ 落在有效 cell 內 → 直接取該 cell 的 dX / dY（corr_type = "raster"）
  └─ 落在 raster 外或 NoData → KDTree 找最近有效 cell（corr_type = "nearest"）
    ↓
X_new = X_ori + dX_k ；Y_new = Y_ori + dY_k
    ↓
更新 geometry，輸出修正後 SHP + 外插點 txt 清單
```

### 修正公式

```
X_new = X_ori + dX_k
Y_new = Y_ori + dY_k
```

> 若實測後方向相反，腳本內已備減號版本註解可切換。

### 輸出

| 檔案 | 說明 |
|------|------|
| `SIGN_0527_修正後_raster_nearest.shp` | 修正後點位，含 `dX_k`、`dY_k`、`corr_type`、`near_dist` 等欄位 |
| `SIGN_外插最近網格清單.txt` | 使用最近網格（非直接取樣）的點位清單，供人工複查 |

### 輸出 SHP 欄位

| 欄位 | 說明 |
|------|------|
| `X_ori` / `Y_ori` | 修正前座標 |
| `X_new` / `Y_new` | 修正後座標 |
| `dX_k` / `dY_k` | 套用的 Kriging 修正量（公尺） |
| `corr_type` | `raster`：直接取樣；`nearest`：最近網格外插 |
| `near_dist` | 外插時與最近有效 cell 的距離（raster 類型為 0） |
| `near_x` / `near_y` | 實際取樣 cell 中心座標 |
| `near_row` / `near_col` | 實際取樣 cell 的 raster 行列索引 |

### 注意事項

- 程式不自動轉換 raster CRS；待修正點座標系需與 raster 一致。
- raster 若標示為 `LOCAL_CS` 但實質為 EPSG:3826，可直接執行。
- `corr_type = nearest` 的點位需人工判斷外插是否合理。

---

## 四、建議執行順序

1. 準備 ROI SHP 與控制點 SHP，確認 `dX`、`dY` 欄位正確。
2. 設定並執行 **腳本一**，產出三個 GeoTIFF（可於 QGIS 檢查 Kriging 結果）。
3. 設定並執行 **腳本二**，產出修正後 SHP 與外插 txt。
4. 對 `corr_type = nearest` 的點位人工複查。