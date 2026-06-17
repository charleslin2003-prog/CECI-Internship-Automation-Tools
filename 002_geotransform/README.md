# geotransform.py

## 功能概述

使用 GDAL 開啟單一 GeoTIFF（DEM），印出完整的空間元資料，包括 GeoTransform、四角範圍、像素對齊推斷、投影座標系、NoData 值與資料型態。

---

## 輸出內容

| 區塊 | 說明 |
|------|------|
| **GeoTransform** | 左上角座標、像素寬高、旋轉參數、影像大小 |
| **四角範圍** | 左/右 X、上/下 Y、寬度與高度（公尺） |
| **像素對齊推斷** | 自動判斷 pixel edge 或 pixel center |
| **投影座標系** | 名稱、類型（投影/地理）、單位 |
| **NoData** | NoData 數值（未定義時顯示提示） |
| **資料型態** | Band 1 的 GDAL 資料型態（如 Float32） |

---

## 像素對齊邏輯

```
左上角 X 座標 mod 像素大小
  ≈ 0          → pixel edge
  ≈ 像素大小/2 → pixel center
  其他         → 不明（顯示餘數）
```

換算結果會同時顯示另一種表示方式的座標，便於核對。

---

## 參數設定

```python
ph = r"路徑\到\你的\dem.tif"
```

只需修改 `ph` 即可使用。

---

## 依賴套件

- `osgeo.gdal`
- `osgeo.osr`
