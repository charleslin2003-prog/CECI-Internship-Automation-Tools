# DEM.py

## 功能概述

批次將原始 DEM GeoTIFF 進行六步驟處理，產製符合規格的成果 DEM（5m 解析度、裁切對齊、補洞、無 NoData）。

---

## 處理流程（每幅）

| 步驟 | 說明 |
|------|------|
| A | 讀入原始 DEM，建立記憶體副本（MEM） |
| B | 極端值遮罩：將 `> 4000` 或 `< -100` 的像素設為 NoData |
| C | 補洞：`gdal.FillNodata`，搜尋距離 `max_search_dist`（預設 1 像素） |
| D | 裁切對齊：依 Excel 圖框範圍執行 `gdal.Translate` |
| E | 實心化：剩餘 NoData / NaN 一律填 `0` |
| F | 寫出 GeoTIFF（DEFLATE 壓縮、Tiled、Float32） |

---

## 參數設定

| 參數 | 說明 |
|------|------|
| `input_dir` | 原始 DEM 資料夾 |
| `output_dir` | 成果輸出資料夾 |
| `excel_path` | 含圖框範圍的 Excel 檔（需有 `左X`、`上Y`、`右X`、`下Y`、`左X2`、`上Y2`、`右X2`、`下Y2` 欄） |
| `max_search_dist` | 補洞最大搜尋距離（像素，預設 `1`） |

解析度從 Excel `B3` 格自動讀取。

---

## Excel 欄位需求

- `圖幅_5K`：圖幅編號（整數）
- `左X` / `上Y`：GeoTransform 寫出用（左上角 edge 座標）
- `左X2` / `上Y2` / `右X2` / `下Y2`：裁切範圍（projWin 用）

---

## 輸出規格

- 格式：GeoTIFF（DEFLATE + Tiled）
- 資料型態：Float32
- NoData：已清除（DeleteNoDataValue）
- 檔名：`{圖幅_5K}dem.tif`

---

## 錯誤處理

異常圖幅記錄至 `處理異常清單.txt`，主迴圈不中斷，最終顯示成功／異常統計。

---

## 依賴套件

- `osgeo.gdal`
- `pandas`
- `numpy`
- `tqdm`
