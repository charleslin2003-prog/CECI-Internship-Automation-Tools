# metashapeXML2IPF_V3.py

## 功能概述

將 Metashape 輸出的 XML（含連接點與控制點）轉換為航測平差軟體所需的 IPF 格式，並加入邊緣緩衝、九宮格選點與補點補償機制。

---

## 主要模組

### 1. 解析模組 `parse_metashape_xml()`

- 使用 `iterparse` 逐節點讀取，避免大檔記憶體爆炸。
- 根據影像尺寸自動查表（`KNOWN_CAMERAS`）判斷像元大小（ps）。
- 分別解析：照片清單、連接點（TiePoint）、控制點（ControlPoint）。

**相機規格表（可擴充）**

| 影像尺寸（寬×高） | 像元大小 (mm) |
|---|---|
| 14592 × 25728 | 0.0039 |
| 20544 × 14016 | 0.00376 |
| 11310 × 17310 | 0.006 |

---

### 2. 選點模組 `select_tie_points_optimized()`

**流程：**

```
對每張影像：
  ① 剔除邊緣 5%（buffer_ratio）的點
  ② 將剩餘點投入 3×3 九宮格
  ③ 每格依「共視影像數↓、距格心距離↑」排序，取前 pts_per_cell 點（預設2）
  ④ 若總選點 < 18，從有效點中補足（依共視數排序）
```

**參數**

| 參數 | 預設 | 說明 |
|------|------|------|
| `pts_per_cell` | `2` | 每格選點數 |
| `buffer_ratio` | `0.05` | 邊緣剔除比例（5%） |

---

### 3. 輸出模組 `export_ipf_files()`

- 控制點在前、連接點在後（`cps + tps`）。
- 座標轉換：像素座標 → 影像座標系（mm），原點為影像中心。
- 輸出格式：每個影像對應一個 `.ipf` 文字檔。

**IPF 欄位**

```
pt_id, val, fid_val, no_obs, l., s., sig_l, sig_s, res_l, res_s, fid_x, fid_y
```

---

## 路徑設定

```python
XML_INPUT  = r"路徑\input.xml"
OUT_FOLDER = r"路徑\output"
```

---

## 執行後輸出

- 各影像 `.ipf` 檔案
- 終端機報告：平均選點數、最低點數、觸發補點影像清單

---

## 依賴套件

- `xml.etree.ElementTree`（標準庫）
- `pandas`
- `collections.defaultdict`（標準庫）
