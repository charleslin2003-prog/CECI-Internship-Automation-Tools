"""
AI 路牌幾何資料分區校正與視覺化品管工具
主程式入口 — TPS 全域版本 v2.0
"""

import geopandas as gpd
import pandas as pd
import sys
from pathlib import Path
from shapely.geometry import Point, LineString

from data_preprocess import DataPreprocessor
from solver_core import SolverCore
from visualization_report import VisualizationReport

# ─── 設定輸入檔案路徑 ────────────────────────────────────────────────
AI_SHP_PATH     = r"d:\14113\驗\測\id\SIGN_0527_SpatialJoin_ExportFeatures.shp"
MANUAL_SHP_PATH = r"t:\AC559\小工具_py\座標改正\DATA\分ROI\修正後.shp"
OUTPUT_SHP_PATH = r"t:\AC559\小工具_py\座標改正\V2\成果v2\AI_corrected_points.shp"
OUTPUT_LINES_PATH = r"t:\AC559\小工具_py\座標改正\V2\成果v2\control_point_lines.shp"       # 控制點連線輸出
OUTPUT_AI_CTRL_PATH = "t:\AC559\小工具_py\座標改正\V2\成果v2\AI_ctrl_points_matchid.shp"    # AI 控制點（含 match_id）
OUTPUT_MANUAL_PATH  = "t:\AC559\小工具_py\座標改正\V2\成果v2\Manual_ctrl_points_matchid.shp" # 人工控制點（含 match_id）
REPORT_DIR      = r"t:\AC559\小工具_py\座標改正\V2\成果v2\error_reports"


# ─── 自動配對參數 ────────────────────────────────────────────────────
MAX_MATCH_DIST = 3.0
ISOLATION_DIST = 2.0
MIN_CTRL_PTS   = 6
ROI_FIELD      = "id"  # ← 修改此處以對應實際的 ROI 欄位名稱

# ─── 自動建立輸出資料夾 ──────────────────────────────────────────────
for _p in [OUTPUT_SHP_PATH, OUTPUT_LINES_PATH,
           OUTPUT_AI_CTRL_PATH, OUTPUT_MANUAL_PATH]:
    Path(_p).parent.mkdir(parents=True, exist_ok=True)


def main():
    print("=" * 60)
    print("  AI 路牌幾何資料分區校正工具  v2.0 (TPS Global)")
    print("=" * 60)

    # ── 1. 讀取資料 ──────────────────────────────────────────────────
    print("\n[1/5] 讀取 SHP 資料...")
    try:
        ai_gdf     = gpd.read_file(AI_SHP_PATH)
        manual_gdf = gpd.read_file(MANUAL_SHP_PATH)
    except Exception as e:
        print(f"[錯誤] 無法讀取 SHP 檔案：{e}")
        sys.exit(1)

    print(f"  AI 點數量：{len(ai_gdf)}")
    print(f"  人工點數量：{len(manual_gdf)}")

    for gdf, name in [(ai_gdf, "AI"), (manual_gdf, "Manual")]:
        if ROI_FIELD not in gdf.columns:
            print(f"[錯誤] {name} 資料缺少 '{ROI_FIELD}' 欄位")
            sys.exit(1)

    roi_list = sorted(ai_gdf[ROI_FIELD].unique())
    print(f"  ROI 區域（欄位：{ROI_FIELD}）：{roi_list}")

    rois_no_manual = [r for r in roi_list
                      if len(manual_gdf[manual_gdf[ROI_FIELD] == r]) == 0]
    if rois_no_manual:
        print(f"\n  [注意] 以下 ROI 無人工點，將依賴全域 TPS 外插：")
        for r in rois_no_manual:
            print(f"    - {r}")

    # ── 2. 全域控制點配對 ─────────────────────────────────────────────
    print("\n[2/5] 全域控制點配對...")
    preprocessor = DataPreprocessor(
        ai_gdf, manual_gdf,
        max_match_dist=MAX_MATCH_DIST,
        isolation_dist=ISOLATION_DIST,
        roi_field=ROI_FIELD
    )

    pairs, _ = preprocessor.build_control_pairs()

    if len(pairs) < MIN_CTRL_PTS:
        print(f"\n[警告] 全域控制點數量不足（{len(pairs)} < {MIN_CTRL_PTS}）")
        answer = input("是否繼續運算？(Y/N): ").strip().upper()
        if answer != "Y":
            print("\n[停止] 正在自動新增 PT 欄位至兩個 SHP 檔案...")
            preprocessor.add_pt_field(AI_SHP_PATH, MANUAL_SHP_PATH)
            print("  已儲存。請在 QGIS/ArcGIS 中手動填寫 PT 欄位，再重新執行。")
            sys.exit(0)

    print(f"  共收集 {len(pairs)} 組全域控制點")

    # ── 3. 全域 TPS 求解 ──────────────────────────────────────────────
    print("\n[3/5] 全域 TPS 求解（含 LOO 交叉驗證）...")
    solver = SolverCore()
    try:
        params, residuals, rmse = solver.solve(pairs)
    except ValueError as e:
        print(f"[錯誤] {e}")
        sys.exit(1)

    print(f"  LOO RMSE = {rmse['total']*100:.2f} cm  "
          f"(X:{rmse['x']*100:.2f}, Y:{rmse['y']*100:.2f})")

    # ── 4. 套用轉換並輸出校正後 SHP ──────────────────────────────────
    print("\n[4/5] 套用 TPS 轉換並輸出 SHP...")
    corrected_gdf = solver.apply_transform(ai_gdf, params)
    corrected_gdf.to_file(OUTPUT_SHP_PATH)
    n_ok      = corrected_gdf["corrected"].sum()
    n_outside = len(corrected_gdf) - n_ok
    print(f"  已儲存：{OUTPUT_SHP_PATH}")
    print(f"  校正成功：{n_ok} 點　凸包外（未校正）：{n_outside} 點")

    # 輸出品管圖
    reporter  = VisualizationReport(output_dir=REPORT_DIR)
    roi_pairs = preprocessor.build_roi_line_pairs(pairs)
    reporter.plot_error_distribution(
        roi="GLOBAL",
        pairs=pairs,
        residuals=residuals,
        rmse=rmse,
        roi_pairs=roi_pairs
    )

    # ── 5. 輸出控制點連線 + 控制點 SHP ───────────────────────────────
    print("\n[5/5] 輸出控制點連線與控制點 SHP...")

    line_records        = []
    ai_ctrl_records     = []
    manual_ctrl_records = []

    for pair in pairs:
        mid    = pair["match_id"]
        ax, ay = pair["ai_xy"]
        mx, my = pair["manual_xy"]
        roi_id = preprocessor._find_roi_of_point(mx, my)

        # ── 連線：match_id 就是這條線的編號 ─────────────────────────
        line_records.append({
            ROI_FIELD:  roi_id,
            "match_id": mid,
            "dist_m":   round(pair.get("dist", 0.0), 4),
            "geometry": LineString([(ax, ay), (mx, my)])
        })

        # ── AI 控制點：取原始列所有屬性 + match_id ───────────────────
        ai_row = ai_gdf.loc[pair["ai_idx"]].copy()
        ai_row["match_id"] = mid
        ai_ctrl_records.append(ai_row)

        # ── 人工控制點：取原始列所有屬性 + match_id ──────────────────
        manual_row = manual_gdf.loc[pair["manual_idx"]].copy()
        manual_row["match_id"] = mid
        manual_ctrl_records.append(manual_row)

    # 輸出連線 SHP
    lines_gdf = gpd.GeoDataFrame(line_records, crs=ai_gdf.crs)
    lines_gdf.to_file(OUTPUT_LINES_PATH)
    print(f"  已儲存：{OUTPUT_LINES_PATH}  （共 {len(lines_gdf)} 條）")

    # 輸出 AI 控制點 SHP
    ai_ctrl_gdf = gpd.GeoDataFrame(ai_ctrl_records, crs=ai_gdf.crs)
    ai_ctrl_gdf["match_id"] = ai_ctrl_gdf["match_id"].astype(int)
    ai_ctrl_gdf.to_file(OUTPUT_AI_CTRL_PATH)
    print(f"  已儲存：{OUTPUT_AI_CTRL_PATH}  （共 {len(ai_ctrl_gdf)} 筆）")

    # 輸出人工控制點 SHP
    manual_ctrl_gdf = gpd.GeoDataFrame(manual_ctrl_records, crs=manual_gdf.crs)
    manual_ctrl_gdf["match_id"] = manual_ctrl_gdf["match_id"].astype(int)
    manual_ctrl_gdf.to_file(OUTPUT_MANUAL_PATH)
    print(f"  已儲存：{OUTPUT_MANUAL_PATH}  （共 {len(manual_ctrl_gdf)} 筆）")

    print(f"\n  品管報告已儲存至：{REPORT_DIR}/")
    print("\n完成！")


if __name__ == "__main__":
    main()