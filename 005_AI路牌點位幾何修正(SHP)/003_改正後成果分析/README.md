# spatial_accuracy_xlsx.py（改正後成果分析）

## 一、功能概述

AI 路牌點位幾何修正流程的最終精度品管模組。以人工測量成果（真值）與 AI 修正後點位進行 1 對 1 空間配對，依各 ROI 分區計算平面 RMSE，輸出格式化 Excel 報表與偏移向量線 SHP，供專案交付與複核使用。

---

## 二、依賴套件

| 套件 | 用途 |
|------|------|
| `geopandas` | SHP 讀寫、空間連接（sjoin） |
| `rasterio` | 克里金 GeoTIFF 取樣 |
| `scipy.spatial.cKDTree` | 高效最近點 / 範圍搜尋 |
| `numpy` / `pandas` | 數值統計 |
| `openpyxl` | Excel 報表格式化輸出 |
| `shapely` | `LineString` 偏移向量線 |

---

## 三、輸入檔案

| 變數 | 說明 |
|------|------|
| `SHP_HUMAN` | 人工測量點（真值，即修正後基準點） |
| `SHP_AI` | AI 修正後點位（經 Kriging 網格位移） |
| `SHP_ROI` | 路面測區範圍面，用於分區歸屬（`id` 欄位） |
| `TIFF_DX` | Kriging 修正場 dX 單 band GeoTIFF（1m） |
| `TIFF_DY` | Kriging 修正場 dY 單 band GeoTIFF（1m） |

---

## 四、核心參數

```python
COL_ROI_ID         = "id"          # ROI SHP 的分區 ID 欄位名稱（sjoin 前使用）
RMSE_THRESHOLD     = 0.5           # 平面 RMSE 門檻（公尺），超過即判定 REDO
DEFAULT_TAIWAN_CRS = "EPSG:3826"   # 遺失 .prj 時的備援座標系（TWD97 TM2）

SEARCH_R1          = 1.0           # 第一階段：最近點搜尋半徑（公尺），找到即配對不做扇形
SEARCH_R2          = 5.0           # 第二階段：扇形搜尋半徑（公尺），第一階段無結果時啟用
SECTOR_HALF_DEG    = 20.0          # 第二階段扇形半角（度），總扇形 = SECTOR_HALF_DEG × 2
```

---

## 五、處理流程

```
STEP 1  載入三圖層，補回遺失 CRS，統一轉為人工點座標系
    ↓
STEP 2  對人工點取克里金 TIFF 的 dX/dY，計算預測跳躍座標與方向
        pred_h_x/y = true_h_x/y + dX_tif/dY_tif（TIF 範圍外的點 dX/dY 補 0）
    ↓
STEP 3  兩階段配對（以 pred 座標為基準）：
          ├─ 第一階段：SEARCH_R1（1m）內有候選 → 全部納入，不做方向篩選
          └─ 第二階段：1m 內無候選 → 擴大至 SEARCH_R2（5m），
                        僅保留落在克里金 dX/dY 方向 ±SECTOR_HALF_DEG 扇形內的候選
                        （nodata 點 dX=dY=0 無方向，直接納入）
        全部候選依殘差由小到大排序 → 貪婪 1 對 1 去重
    ↓
STEP 4  計算觀測偏移：
        dX_obs = true_a_x − true_h_x
        dY_obs = true_a_y − true_h_y
        dist2d_obs = sqrt(dX_obs² + dY_obs²)
        依 ROI（sjoin intersects）分組計算 mean_2d、RMSE
    ↓
STEP 5  輸出偏移向量線 SHP（offset_vectors.shp）
    ↓
STEP 6  寫入格式化 Excel 報表
```

---

## 六、配對邏輯

```
每個 AI 點：
  ├─ SEARCH_R1（1m）內有人工點？
  │    YES → 全部納入候選（不看角度）
  │
  └─ NO → 擴大到 SEARCH_R2（5m）
           ├─ 有克里金方向（dX/dY 非零）→ 只保留 ±SECTOR_HALF_DEG 扇形內候選
           └─ 無克里金方向（nodata，dX=dY=0）→ 直接納入
  → 所有候選依殘差排序，貪婪 1 對 1 去重（每個人工點 / AI 點各只用一次）
```

> 先以克里金修正場估算人工點的「預測跳躍位置」，消除系統性形變偏移後再搜尋，提升配對正確性。

---

## 七、輸出檔案

| 變數 / 檔名 | 說明 |
|------|------|
| `OUT_XLSX`（`spatial_accuracy_report.xlsx`） | 精度統計報表（雙分頁） |
| `OUT_SHP_LINES`（`offset_vectors.shp`） | 1 對 1 偏移向量線，含 `roi_id`、`dX_obs`、`dY_obs`、`dist2d` |

### Excel 報表結構

**Sheet 1：ROI 精度統計表**

| 欄位 | 說明 |
|------|------|
| ROI分區ID (id) | 測區 ROI 編號 |
| 唯一配對點數 | 該 ROI 內成功配對點數 |
| 幾何平均偏移 (m) | 配對點對的平均 2D 距離 |
| 幾何平面 RMSE (m) | 配對點對的平面 RMSE |
| 判定結果 | `PASS (合格)` / `REDO (需重算)` / `N/A (無配對點)` |

- REDO 行：整列紅底，判定欄深紅字。
- PASS 行：判定欄綠底綠字，其餘奇數列套斑馬紋。
- 底部合計列：總點數 SUM、平均偏移與 RMSE 的 AVERAGE。

**Sheet 2：需重算缺陷清單**

僅列出判定為 `REDO` 的 ROI，供快速定位與派工。

---

## 八、精度判定標準

| 指標 | 門檻 | 判定 |
|------|------|------|
| 平面 RMSE | ≤ 0.5 m | ✅ PASS（合格） |
| 平面 RMSE | > 0.5 m | ❌ REDO（需重算） |
| 無配對點 | — | N/A（無配對點） |

判定僅依幾何量測，不納入屬性欄位或信賴區間。

---

## 九、注意事項

- 三個輸入 SHP 若缺 `.prj`，程式自動以 `set_crs()` 補回 `EPSG:3826` 並印警告。
- CRS 不一致時，AI 點與 ROI 自動轉換至人工點座標系。
- 克里金 TIFF 為 `LOCAL_CS` 時不執行 CRS 轉換，直接以原始 XY 取樣；請確認 TIF 與 SHP 同座標系。
- 人工點落在 ROI 邊界（同時符合兩分區）時，保留第一個匹配分區。
- 人工點落在 Kriging 網格範圍外時，`dX_tif/dY_tif` 補 0，該點第二階段不套扇形限制。
- `OUT_XLSX` 若指定子目錄，程式會自動建立；請確認有寫入權限。
- sjoin 前將 ROI 的 `id` 改名為 `roi_id`，避免與 AI 點同名欄位衝突。