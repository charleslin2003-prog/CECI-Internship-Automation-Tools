# DEM.py

## 一、功能概述

批次將原始 DEM GeoTIFF 進行六步驟處理，產製符合規格的成果 DEM（解析度由 Excel 讀取、裁切對齊圖框、補洞、無 NoData）。異常圖幅記錄至清單，主迴圈不中斷。

---

## 二、依賴套件

| 套件 | 用途 |
|------|------|
| `osgeo.gdal` | DEM 讀寫、補洞、裁切、壓縮輸出 |
| `pandas` | 讀取 Excel 圖框參數 |
| `numpy` | 陣列運算、極端值遮罩 |
| `tqdm` | 進度條 |

---

## 三、處理流程（每幅）

| 步驟 | 說明 |
|------|------|
| A | 讀入原始 DEM，建立記憶體副本（MEM），盡早釋放原始檔案鎖定 |
| B | 極端值遮罩：將 `> 4000` 或 `< -100` 的像素設為 NoData |
| C | 補洞：`gdal.FillNodata`，搜尋距離 `max_search_dist`（預設 1 像素） |
| D | 裁切對齊：依 Excel 圖框 `[左X2, 上Y2, 右X2, 下Y2]` 執行 `gdal.Translate` |
| E | 實心化：剩餘 NoData / NaN 一律填 `0` |
| F | 寫出 GeoTIFF（`COMPRESS=DEFLATE`、`TILED=YES`、Float32），並 `DeleteNoDataValue` |

---

## 四、參數設定

| 參數 | 預設 | 說明 |
|------|------|------|
| `input_dir` | `"DEM 修正"` | 原始 DEM 資料夾 |
| `output_dir` | `"成果"` | 成果輸出資料夾 |
| `excel_path` | — | 含圖框範圍的 Excel 檔 |
| `max_search_dist` | `1` | 補洞最大搜尋距離（像素） |

> 解析度自 Excel 工作表「121正射用圖框」的 **B3** 儲存格（`iloc[2, 1]`）自動讀取。

---

## 五、Excel 欄位需求（工作表：121正射用圖框）

正式欄位由第 3 列（`header=2`）起算，須含：

| 欄位 | 用途 |
|------|------|
| `圖幅_5K` | 圖幅編號（整數，轉字串作檔名比對） |
| `左X` / `上Y` | 寫出 GeoTransform 用（左上角 edge 座標） |
| `左X2` / `上Y2` / `右X2` / `下Y2` | 裁切範圍（`projWin`） |

---

## 六、輸出規格

- 格式：GeoTIFF（DEFLATE + Tiled）
- 資料型態：Float32
- NoData：已清除（`DeleteNoDataValue`）
- GeoTransform：以 `左X / 上Y` 與正負 `resolution` 強制寫入，避免像素飄移
- 檔名：`{圖幅_5K}dem.tif`

---

## 七、錯誤處理

- 找不到原始檔、GDAL 無法開啟、Translate 失敗、處理異常等，皆回傳錯誤訊息並續跑。
- 全部完成後印出「成功／異常」統計。
- 異常清單寫入 `{output_dir}/處理異常清單.txt`。

---

## 八、注意事項

- 原始 DEM 檔名須為 `{圖幅_5K}dem.tif`（例如 `97221dem.tif`）。
- Excel 解析度取自 B3，與 GeoTransform 寫出的像素大小一致。
- 極端值門檻（4000 / -100）為硬編，依資料特性可自行調整。