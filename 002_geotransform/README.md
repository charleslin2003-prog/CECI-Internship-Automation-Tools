# geotransform.py

## 一、功能概述

使用 GDAL 開啟單一 GeoTIFF（DEM），於終端機印出完整空間元資料：GeoTransform、四角範圍、像素對齊推斷、投影座標系、NoData 值與資料型態。純診斷用途，只讀不寫。

---

## 二、依賴套件

| 套件 | 用途 |
|------|------|
| `osgeo.gdal` | 開啟影像、讀取 GeoTransform 與波段 |
| `osgeo.osr` | 解析投影座標系（SpatialReference） |

---

## 三、輸出內容

| 區塊 | 說明 |
|------|------|
| **GeoTransform** | 左上角 X/Y（edge）、像素寬高、旋轉參數 X/Y、影像欄列數 |
| **四角範圍** | 左/右 X、上/下 Y，以 pixel edge 為準；寬度與高度（公尺） |
| **像素對齊推斷** | 自動判斷 pixel edge 或 pixel center，並換算另一種表示 |
| **投影座標系** | 名稱、類型（投影 / 地理）、單位 |
| **NoData** | NoData 數值（未定義時顯示「未定義」） |
| **資料型態** | Band 1 的 GDAL 資料型態（如 Float32） |

---

## 四、像素對齊邏輯

```
左上角 X 座標 mod 像素大小：
  ≈ 0            → pixel edge
  ≈ 像素大小 / 2 → pixel center
  其他           → 不明（顯示餘數）
```

- 判定為 pixel edge 時，加印「左上像素 center」座標。
- 判定為 pixel center 時，加印「左上 edge」座標。

---

## 五、參數設定

```python
ph = r"路徑\到\你的\dem.tif"   # 僅需修改此行
```

---

## 六、注意事項

- 程式僅讀取與輸出資訊，不會修改或寫出任何檔案。
- 容差以 `1e-6` 判斷對齊；非標準對齊會顯示實際餘數供人工判讀。
- 旋轉參數（gt[2]、gt[4]）非 0 時代表影像有旋轉，範圍計算仍以 gt[1]/gt[5] 推算。