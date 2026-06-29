# main.py（控制點萃取及分析）

> 配對核心位於同目錄 `data_preprocess.py`（類別 `DataPreprocessor`），由 `main.py` 設定路徑與參數後呼叫。

## 一、功能概述

從 AI 偵測路牌點與人工量測點中萃取配對控制點，輸出配對連線 SHP、含 `match_id` 的 AI / 人工控制點 SHP，以及補點記錄與 ROI 稀疏報告（xlsx）。支援 PT 欄位強制配對與自動配對兩種模式，PT 模式後可選兩階段補點。

---

## 二、依賴套件

| 套件 | 用途 |
|------|------|
| `geopandas` | SHP 讀寫 |
| `pandas` | xlsx 報表（openpyxl 引擎） |
| `numpy` | 距離與孤立點運算 |
| `shapely` | `LineString` 連線、`MultiPoint` / `Point`、`voronoi_diagram` |

對應 `requirements.txt`：`geopandas>=0.14.0`、`shapely>=2.0.0`、`numpy>=1.24.0`、`pandas>=2.0.0`

---

## 三、輸入與參數（main.py 頂部）

| 參數 | 預設 | 說明 |
|------|------|------|
| `AI_SHP_PATH` | — | AI 偵測點 SHP |
| `MANUAL_SHP_PATH` | — | 人工量測點 SHP |
| `SURVEY_SHP_PATH` | `""` | 測區面資料 SHP，可留空（改用 AI 點凸包估面積） |
| `MAX_MATCH_DIST` | `3.0` | 最大配對距離（公尺） |
| `ISOLATION_DIST` | `2.0` | 孤立點判斷距離（公尺） |
| `ROI_FIELD` | `"id"` | ROI 欄位名稱（依實際 SHP 修改） |
| `PT_FIELD` | `"PT"` | 控制點配對編號欄位名稱 |
| `VORONOI_STOP_RATIO` | `2.0` | 補點停止倍率（建議 1.2～5.0） |

---

## 四、配對流程

### 模式判斷

```
兩個 SHP 都有 PT 欄位且有值？
  ├─ 雙邊有值 → 詢問是否作為配對編號（Y/N）
  ├─ 單邊有值 → 警告，改走自動模式
  └─ 無 PT 欄位 → 直接自動模式
```

- **PT 模式**：以相同 PT 值強制配對，`dist` 固定 0.0；完成後詢問是否補點。
- **自動模式**：孤立點篩選 → 最近鄰配對 → 雙向一對一去重。

### 兩階段補點（PT 模式後選 Y）

```
第一輪：孤立點篩選（批次）
  排除已配對點 → 孤立篩選（> ISOLATION_DIST）→ 最近鄰（≤ MAX_MATCH_DIST）→ 雙向去重
  第一輪後均勻度檢查：最大 Voronoi cell < 基準面積 / 控制點數 × VORONOI_STOP_RATIO → 均勻則略過第二輪

第二輪：Voronoi 迭代（逐輪）
  每輪：計算 Voronoi 找最大 cell → 全域剩餘孤立點篩選
        → 最大 cell 內優先排序 → 批次配對（雙向去重）→ 補入
  停止條件（任一）：分佈均勻 / 候選人工點用完 / 無孤立候選 / 無可配對候選（超距離閾值）
```

> 基準面積優先採實際測區面積（`SURVEY_SHP_PATH`），否則用控制點凸包面積。

---

## 五、`VORONOI_STOP_RATIO` 區間

| 值 | 行為 |
|----|------|
| 1.0 | 幾乎不停，補到候選用完 |
| 1.2～1.5 | 嚴格，適合高精度需求 |
| **2.0（預設）** | 中等，最大空隙不超過平均 2 倍 |
| 3.0～4.0 | 寬鬆，只補明顯稀疏區域 |
| 5.0+ | 非常寬鬆，接近不補 |

---

## 六、輸出檔案

| 檔案 | 說明 |
|------|------|
| `control_point_lines.shp` | 配對連線（AI → 人工），含 `match_id`、`dist_m` |
| `AI_ctrl_points_matchid.shp` | AI 控制點，含原始屬性 + `match_id`、`X_new`、`Y_new`、`dx`、`dy` |
| `Manual_ctrl_points_matchid.shp` | 人工控制點，含原始屬性 + `match_id` |
| `supplement_log.xlsx` | Sheet1 補點記錄；Sheet2 ROI 稀疏報告 |

### `AI_ctrl_points_matchid.shp` 新增欄位

| 欄位 | 說明 |
|------|------|
| `match_id` | 配對流水號（從 1 起） |
| `X_new` / `Y_new` | 對應人工點座標 |
| `dx` / `dy` | 人工點座標 − AI 點座標 |

### xlsx 內容

- **Sheet 1 補點記錄**：輪次、迭代次數、方法（孤立點篩選 / Voronoi迭代）、人工點 X/Y、AI 點 X/Y、配對距離。
- **Sheet 2 ROI 稀疏報告**（需提供 `SURVEY_SHP_PATH`）：ROI、控制點數、ROI 面積、密度、是否為最大 cell 所在 ROI、是否密度低於全域平均。

---

## 七、注意事項

- 程式以 `input()` 互動詢問（PT 模式 / 補點），批次自動化執行時會卡住等待輸入。
- 找不到任何配對時，會自動在兩個 SHP 新增空白 `PT` 欄位並結束，提示在 GIS 中手動填寫後重跑。
- `ROI_FIELD` 須對應實際 SHP 欄位名稱（預設 `"id"`）。
- 未提供測區面資料時，ROI 稀疏報告無法產生，面積基準改用 AI 點凸包。

**1. 安裝套件**
```bash
pip install -r requirements.txt
```

**2. 修改 `main.py` 頂部路徑與參數**

**3. 執行**
```bash
python main.py
```

