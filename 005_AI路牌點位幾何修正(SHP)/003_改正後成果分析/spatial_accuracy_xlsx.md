# spatial_accuracy_xlsx.py

## 功能概述

本腳本為 **AI 路牌點位幾何修正流程的最終精度品管模組**。

以人工測量成果（真值）與 AI 修正後點位進行 1 對 1 空間配對，計算各 ROI 分區的平面 RMSE，並輸出格式化 Excel 報表與偏移向量線 SHP，供專案交付與複核使用。

---

## 執行環境

| 套件 | 用途 |
|---|---|
| `geopandas` | SHP 讀寫、空間連結 |
| `rasterio` | 克里金 GeoTIFF 取樣 |
| `scipy` | cKDTree 空間近鄰搜尋 |
| `numpy` / `pandas` | 數值統計 |
| `openpyxl` | Excel 報表格式化輸出 |
| `shapely` | LineString 向量線幾何 |

---

## 輸入檔案

| 變數 | 說明 |
|---|---|
| `SHP_HUMAN` | 人工測量點（真值），即修正後基準點 |
| `SHP_AI` | AI 修正後點位（經 Kriging 網格位移） |
| `SHP_ROI` | 路面測區範圍面，用於分區歸屬（`id` 欄位） |
| `TIFF_DX` | Kriging 修正場 dX 單 band GeoTIFF（1m 解析度） |
| `TIFF_DY` | Kriging 修正場 dY 單 band GeoTIFF（1m 解析度） |

---

## 輸出檔案

| 變數 | 說明 |
|---|---|
| `OUT_XLSX` | 精度統計報表 `spatial_accuracy_report.xlsx` |
| `OUT_SHP_LINES` | 1 對 1 偏移向量線 `offset_vectors.shp` |

### Excel 報表結構

**Sheet 1：ROI精度統計表**

| 欄位 | 說明 |
|---|---|
| ROI分區ID (id) | 測區 ROI 編號 |
| 唯一配對點數 | 該 ROI 內成功配對點數 |
| 幾何平均偏移 (m) | 配對點對之平均 2D 距離 |
| 幾何平面 RMSE (m) | 配對點對之平面 RMSE |
| 判定結果 | `PASS (合格)` / `REDO (需重算)` |

**Sheet 2：需重算缺陷清單**

僅列出 `REDO` 的 ROI，供複核快速定位問題分區。

---

## 核心參數

```python
RMSE_THRESHOLD    = 1.0   # 平面 RMSE 門檻（公尺），超過即判定 REDO
MAX_DISTANCE_LIMIT = 5.0  # 配對搜尋半徑上限（公尺）
COL_ROI_ID        = "id"  # ROI SHP 的分區 ID 欄位名稱
```

---

## 處理流程

```
STEP 1  載入 SHP，同步 CRS
        ↓
STEP 2  對人工點取樣 Kriging TIF → 取得 dX_tif / dY_tif
        計算預測跳躍座標 pred_h_x/y = true_h_x/y + dX_tif/dY_tif
        ↓
STEP 3  以 pred_h_x/y 為圓心，在 MAX_DISTANCE_LIMIT 內搜尋最近 AI 點
        貪婪排序去重 → 1 對 1 唯一配對
        ↓
STEP 4  計算觀測誤差：
        dX_obs = true_a_x - true_h_x
        dY_obs = true_a_y - true_h_y
        dist2d_obs = sqrt(dX_obs² + dY_obs²)
        按 ROI 分區 groupby → 計算 mean_2d、RMSE
        ↓
STEP 5  輸出偏移向量線 SHP（offset_vectors.shp）
        ↓
STEP 6  寫入格式化 Excel 報表
```

---

## 配對邏輯說明

本腳本採用**兩階段配對**，以提升精度評估的正確性：

1. **Kriging 輔助跳躍**：先對人工點套用 Kriging 修正場，估算其對應 AI 點的預測位置，消除系統性形變偏移的干擾。
2. **貪婪 1 對 1 去重**：在預測座標周圍 `MAX_DISTANCE_LIMIT` 公尺內，依殘差由小到大排序，確保每個人工點與 AI 點只配對一次，不重複使用。

> 若人工點落於 Kriging 網格範圍外，`dX_tif / dY_tif` 自動補零，直接以原始座標搜尋。

---

## 精度判定標準

| 指標 | 門檻 | 判定 |
|---|---|---|
| 平面 RMSE | ≤ 1.0 m | ✅ PASS（合格） |
| 平面 RMSE | > 1.0 m | ❌ REDO（需重算） |

判定僅依據幾何量測，不納入屬性欄位或信賴區間。

---

## 注意事項

- `SHP_HUMAN`、`SHP_AI`、`SHP_ROI` 的 CRS 若不一致，腳本會自動將 AI 點與 ROI 轉換至人工點的 CRS。
- Kriging TIF 若 CRS 為 `LOCAL_CS`（如 GDAL 匯出的無名投影），腳本**不執行**自動 CRS 轉換，直接以原始 XY 取樣，請確認 TIF 與 SHP 使用相同坐標系（建議 TWD97 TM2 / EPSG:3826）。
- `OUT_XLSX` 若指定子目錄，腳本會自動建立目錄；請確認目前使用者有寫入權限。

---

## 在整體流程中的位置

```
001_控制點萃取及分析/
    main.py                   ← 控制點配對、輸出 match_id SHP
    data_preprocess.py

002_克里金法/
    01_dXdY_Correction_Kriging_Grid.py   ← 建立 dX/dY Kriging 修正網格 TIF
    02_CorrectPts_byKriging_Grid.py      ← 套用修正網格，輸出修正後 SHP

003_改正後成果分析/
    spatial_accuracy_xlsx.py  ← ★ 本腳本：最終精度評估與品管報表
```
