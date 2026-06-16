"""
AI 路牌控制點萃取工具
功能：控制點配對 → 輸出連線 SHP + AI/人工控制點 SHP（含 match_id）+ 補點 log xlsx
"""

import sys
import geopandas as gpd
import pandas as pd
from pathlib import Path
from shapely.geometry import LineString

from data_preprocess import DataPreprocessor

# ─── 輸入檔案路徑 ────────────────────────────────────────────────────
AI_SHP_PATH     = r"修正前.shp"
MANUAL_SHP_PATH = r"修正後.shp"
SURVEY_SHP_PATH = r"ROI_V01.shp"   # 實際測區面資料（可留空 ""）

# ─── 輸出路徑 ────────────────────────────────────────────────────────
OUTPUT_DIR           = r"ctrl_output"
OUTPUT_LINES_PATH    = r"ctrl_output_V1\control_point_lines.shp"
OUTPUT_AI_CTRL_PATH  = r"ctrl_output_V1\AI_ctrl_points_matchid.shp"
OUTPUT_MAN_CTRL_PATH = r"ctrl_output_V1\Manual_ctrl_points_matchid.shp"
OUTPUT_LOG_PATH      = r"supplement_log.xlsx"

# ─── 配對參數 ────────────────────────────────────────────────────────
MAX_MATCH_DIST      = 3.0    # 最大配對距離（公尺）
ISOLATION_DIST      = 2.0    # 孤立點判斷距離（公尺）
ROI_FIELD           = "id"   # ROI 欄位名稱（視實際 SHP 欄位修改）
PT_FIELD            = "PT"   # 控制點配對編號欄位名稱（預設 "PT"）
VORONOI_STOP_RATIO  = 2.0    # 補點停止閾值：最大 cell < 平均面積 × N 倍時停止


def load_survey(path: str):
    """
    讀取測區面資料 SHP，回傳 (GeoDataFrame, 總面積)。
    路徑為空或讀取失敗時回傳 (None, None)。
    """
    if not path:
        return None, None
    try:
        gdf  = gpd.read_file(path)
        area = float(gdf.geometry.area.sum())
        print(f"  測區面積（{len(gdf)} 個 ROI 合計）：{area:.1f} m²")
        return gdf, area
    except Exception as e:
        print(f"  [警告] 無法讀取測區面資料：{e}，改用 AI 點凸包估算。")
        return None, None


def main():
    print("=" * 55)
    print("  AI 路牌控制點萃取工具")
    print("=" * 55)

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    # ── 1. 讀取 SHP ───────────────────────────────────────────────────
    print("\n[1/3] 讀取 SHP 資料...")
    try:
        ai_gdf     = gpd.read_file(AI_SHP_PATH)
        manual_gdf = gpd.read_file(MANUAL_SHP_PATH)
    except Exception as e:
        print(f"[錯誤] 無法讀取 SHP：{e}")
        sys.exit(1)

    print(f"  AI 點數量：{len(ai_gdf)}")
    print(f"  人工點數量：{len(manual_gdf)}")

    survey_gdf, survey_area = load_survey(SURVEY_SHP_PATH)

    # ── 2. 控制點配對 ─────────────────────────────────────────────────
    print("\n[2/3] 控制點配對...")
    preprocessor = DataPreprocessor(
        ai_gdf, manual_gdf,
        max_match_dist=MAX_MATCH_DIST,
        isolation_dist=ISOLATION_DIST,
        roi_field=ROI_FIELD,
        pt_field=PT_FIELD,
        voronoi_stop_ratio=VORONOI_STOP_RATIO,
        survey_area=survey_area
    )

    pairs, _, supp_log = preprocessor.build_control_pairs()

    if len(pairs) == 0:
        print("[警告] 未找到任何配對，請確認參數設定或改用 PT 欄位模式。")
        preprocessor.add_pt_field(AI_SHP_PATH, MANUAL_SHP_PATH)
        sys.exit(0)

    # ── 3. 輸出 SHP ───────────────────────────────────────────────────
    print("\n[3/3] 輸出 SHP...")

    line_records        = []
    ai_ctrl_records     = []
    manual_ctrl_records = []

    for pair in pairs:
        mid    = pair["match_id"]
        ax, ay = pair["ai_xy"]
        mx, my = pair["manual_xy"]

        line_records.append({
            "match_id": mid,
            "dist_m":   round(pair.get("dist", 0.0), 4),
            "geometry": LineString([(ax, ay), (mx, my)])
        })

        ai_row = ai_gdf.loc[pair["ai_idx"]].copy()
        ai_row["match_id"] = mid
        ai_row["X_new"]    = round(mx, 4)
        ai_row["Y_new"]    = round(my, 4)
        ai_row["dX"]       = round(mx - ax, 4)
        ai_row["dY"]       = round(my - ay, 4)
        ai_ctrl_records.append(ai_row)

        man_row = manual_gdf.loc[pair["manual_idx"]].copy()
        man_row["match_id"] = mid
        manual_ctrl_records.append(man_row)

    lines_gdf = gpd.GeoDataFrame(line_records, crs=ai_gdf.crs)
    lines_gdf.to_file(OUTPUT_LINES_PATH)
    print(f"  連線 SHP：{OUTPUT_LINES_PATH}  （{len(lines_gdf)} 條）")

    ai_ctrl_gdf = gpd.GeoDataFrame(ai_ctrl_records, crs=ai_gdf.crs)
    ai_ctrl_gdf["match_id"] = ai_ctrl_gdf["match_id"].astype(int)
    ai_ctrl_gdf.to_file(OUTPUT_AI_CTRL_PATH)
    print(f"  AI 控制點 SHP：{OUTPUT_AI_CTRL_PATH}  （{len(ai_ctrl_gdf)} 筆）")

    man_ctrl_gdf = gpd.GeoDataFrame(manual_ctrl_records, crs=manual_gdf.crs)
    man_ctrl_gdf["match_id"] = man_ctrl_gdf["match_id"].astype(int)
    man_ctrl_gdf.to_file(OUTPUT_MAN_CTRL_PATH)
    print(f"  人工控制點 SHP：{OUTPUT_MAN_CTRL_PATH}  （{len(man_ctrl_gdf)} 筆）")

    # ── 4. 輸出 xlsx（補點 log + ROI 稀疏報告） ───────────────────────
    with pd.ExcelWriter(OUTPUT_LOG_PATH, engine="openpyxl") as writer:

        # Sheet 1：補點記錄
        if supp_log:
            rows = []
            for p in supp_log:
                mx, my = p["manual_xy"]
                ax, ay = p["ai_xy"]
                rows.append({
                    "輪次":       p.get("round",  "-"),
                    "迭代次數":   p.get("iter",   "-"),
                    "方法":       p.get("method", "-"),
                    "人工點_X":   round(mx, 4),
                    "人工點_Y":   round(my, 4),
                    "AI點_X":     round(ax, 4),
                    "AI點_Y":     round(ay, 4),
                    "配對距離_m": round(p.get("dist", 0.0), 4),
                })
            pd.DataFrame(rows).to_excel(writer, sheet_name="補點記錄", index=False)
            print(f"  補點記錄：{len(rows)} 筆")
        else:
            pd.DataFrame([{"說明": "無補點記錄"}]).to_excel(
                writer, sheet_name="補點記錄", index=False)

        # Sheet 2：ROI 稀疏報告
        roi_report = preprocessor.get_sparse_roi_report(pairs, survey_gdf)
        if roi_report:
            df_roi = pd.DataFrame(roi_report)
            df_roi["最大cell所在ROI"] = df_roi["最大cell所在ROI"].map(
                {True: "⚠ 是", False: ""})
            df_roi["密度低於全域平均"] = df_roi["密度低於全域平均"].map(
                {True: "⚠ 是", False: ""})
            df_roi.to_excel(writer, sheet_name="ROI稀疏報告", index=False)
            n_sparse = ((df_roi["最大cell所在ROI"] == "⚠ 是") |
                        (df_roi["密度低於全域平均"] == "⚠ 是")).sum()
            print(f"  ROI 稀疏報告：{len(df_roi)} 個 ROI，其中 {n_sparse} 個需注意")
        else:
            pd.DataFrame([{"說明": "未提供測區面資料，無法產生報告"}]).to_excel(
                writer, sheet_name="ROI稀疏報告", index=False)

    print(f"  xlsx 已儲存：{OUTPUT_LOG_PATH}")
    print("\n完成！")


if __name__ == "__main__":
    main()