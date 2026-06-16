# 控制點萃取工具

從 AI 偵測路牌點與人工量測點中，萃取配對控制點並輸出 SHP 與品管報告。

## 目錄結構

```
ctrl_extract/
├── main.py             # 主程式（設定路徑與參數）
├── data_preprocess.py  # 配對與補點核心邏輯
├── requirements.txt
└── README.md
```

## 輸出檔案

| 檔案 | 說明 |
|------|------|
| `control_point_lines.shp` | 配對連線（AI → 人工點），含 `match_id`、`dist_m` |
| `AI_ctrl_points_matchid.shp` | AI 控制點，含原始屬性 + `match_id`、`X_new`、`Y_new`、`dx`、`dy` |
| `Manual_ctrl_points_matchid.shp` | 人工控制點，含原始屬性 + `match_id` |
| `supplement_log.xlsx` | 補點記錄（Sheet1）+ ROI 稀疏報告（Sheet2） |

### `AI_ctrl_points_matchid.shp` 新增欄位

| 欄位 | 說明 |
|------|------|
| `match_id` | 配對流水號（從 1 開始） |
| `X_new` | 對應人工點 X 座標 |
| `Y_new` | 對應人工點 Y 座標 |
| `dx` | 人工點 X − AI 點 X |
| `dy` | 人工點 Y − AI 點 Y |

## 使用方式

**1. 安裝套件**
```bash
pip install -r requirements.txt
```

**2. 修改 `main.py` 頂部路徑與參數**

```python
AI_SHP_PATH     = r"你的AI點.shp"
MANUAL_SHP_PATH = r"你的人工點.shp"
SURVEY_SHP_PATH = r"你的測區面資料.shp"  # 可留空 ""

MAX_MATCH_DIST     = 3.0   # 最大配對距離（公尺）
ISOLATION_DIST     = 2.0   # 孤立點判斷距離（公尺）
ROI_FIELD          = "id"  # SHP 中的 ROI 欄位名稱
PT_FIELD           = "PT"  # 控制點配對編號欄位名稱
VORONOI_STOP_RATIO = 2.0   # 補點停止倍率（建議 1.2～5.0）
```

**3. 執行**
```bash
python main.py
```

## 配對流程

### 主模式判斷

```
兩個 SHP 都有 PT 欄位且有值？
  ├─ 雙邊有值 → 詢問是否作為配對編號（Y/N）
  ├─ 單邊有值 → 警告，改走自動模式
  └─ 無 PT 欄位 → 直接自動模式
```

### PT 模式

以相同 PT 值強制配對，`dist` 固定為 0.0。配對完成後詢問是否補點。

### 自動模式

孤立點篩選 → 最近鄰配對 → 雙向一對一去重。

### 兩階段補點（PT 模式後選 Y）

**第一輪：孤立點篩選（批次）**
排除已配對點 → 孤立點篩選（> `ISOLATION_DIST`）→ 最近鄰配對（≤ `MAX_MATCH_DIST`）→ 雙向去重 → 批次補入

**第一輪後均勻度檢查**
最大 Voronoi cell < 基準面積 / 控制點數 × `VORONOI_STOP_RATIO` → 均勻，略過第二輪

**第二輪：Voronoi 迭代（逐輪）**

每輪迭代步驟：
1. 計算當前控制點 Voronoi，找最大 cell
2. 全域剩餘人工點做孤立點篩選
3. 最大 cell 內的孤立點優先排序
4. 批次配對（雙向去重），補入本輪結果

停止條件（任一觸發）：分佈已均勻 / 候選人工點用完 / 無孤立候選點 / 無可配對候選點

## 參數說明

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `MAX_MATCH_DIST` | `3.0` | AI 點與人工點最大配對距離（公尺） |
| `ISOLATION_DIST` | `2.0` | 人工點孤立判斷距離（公尺） |
| `PT_FIELD` | `"PT"` | 配對編號欄位名稱 |
| `VORONOI_STOP_RATIO` | `2.0` | 補點停止倍率（1.2～5.0） |
| `SURVEY_SHP_PATH` | `""` | 測區面資料路徑，留空改用 AI 點凸包 |

### `VORONOI_STOP_RATIO` 區間

| 值 | 行為 |
|----|------|
| 1.0 | 幾乎不停，補到候選點用完 |
| 1.2～1.5 | 嚴格，適合高精度需求 |
| **2.0（預設）** | 中等，最大空隙不超過平均 2 倍 |
| 3.0～4.0 | 寬鬆，只補明顯稀疏區域 |
| 5.0+ | 非常寬鬆，效果接近不補 |

## xlsx 內容

**Sheet 1：補點記錄**

| 欄位 | 說明 |
|------|------|
| 輪次 | 1＝孤立點篩選，2＝Voronoi 迭代 |
| 迭代次數 | 第二輪的第幾次迭代（第一輪為 0） |
| 方法 | 孤立點篩選 / Voronoi迭代 |
| 人工點_X/Y | 人工點座標 |
| AI點_X/Y | 配對 AI 點座標 |
| 配對距離_m | 配對距離（公尺） |

**Sheet 2：ROI 稀疏報告**（需提供 `SURVEY_SHP_PATH`）

| 欄位 | 說明 |
|------|------|
| ROI | ROI 編號 |
| 控制點數 | 該 ROI 內的控制點數量 |
| ROI面積_m2 | ROI 面積（平方公尺） |
| 密度_點每萬m2 | 控制點密度 |
| 最大cell所在ROI | ⚠ 是，最大 Voronoi cell 落在此 ROI |
| 密度低於全域平均 | ⚠ 是，密度低於全域平均 |