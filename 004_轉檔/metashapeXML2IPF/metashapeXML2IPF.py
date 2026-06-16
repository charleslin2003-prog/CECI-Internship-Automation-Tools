# -*- coding: utf-8 -*-
"""
14220-電子地圖 專業優化版 (效能提昇 + 點數補償 + 補點回報版)
新增功能：
1. Edge Buffer：剔除影像邊緣 5% 範圍內的點位，降低畸變影響。
2. Distribution Report：自動統計每張影像的選點數量，方便品管。
3. 效能優化：加速大檔處理。
4. 點數補償機制：若九宮格選不滿 18 點，則從全圖(扣除邊緣)中挑選共點數最高的點補足。
5. 補點回報：在執行完畢後，列出觸發補點機制的影像清單。
"""
import time
import xml.etree.ElementTree as ET
import pandas as pd
from collections import defaultdict
import os
from pathlib import Path

# ==========================================
# --- 使用者設定區 (路徑設定) ---
# ==========================================
# 請修改為你的路徑
XML_INPUT = r".xml"            # XML 輸入路徑
OUT_FOLDER = r"成果"     # IPF 成果輸出路徑


# ==========================================
# 1. 基礎解析模組，相機規格資料庫 (在此新增或修改相機)
# ==========================================
KNOWN_CAMERAS = {
    tuple(sorted((14592, 25728))): 0.0039,
    tuple(sorted((20544, 14016))): 0.00376,
    tuple(sorted((11310, 17310))): 0.006
}

#根據影像的寬與高，自動判斷並回傳對應相機的「像元大小（Pixel Size）」
def get_ps_by_dims(w, h):
    key = tuple(sorted((w, h)))
    return KNOWN_CAMERAS.get(key)

#資料引擎
def parse_metashape_xml(xml_path):
    """
    讀取 Metashape XML，並根據影像尺寸自動判斷相機型號與 ps。
    分別解析出照片、連接點(TiePoint)與控制點(ControlPoint)。
    """

    photos, tps, cps = [], [], []   # 存放連接點、存放控制點
    tp_counter = 1                  #tps編碼起始號
    current_w, current_h, current_ps = 0, 0, None

    print(f"正在讀取 XML: {Path(xml_path).name}...")
    for event, elem in ET.iterparse(xml_path, events=("end",)):
        tag = elem.tag
        if tag.endswith("ImageDimensions"): #影像規格擷取
            w_elem, h_elem = elem.find('{*}Width'), elem.find('{*}Height')
            w = int(w_elem.text) if w_elem is not None and w_elem.text else 0
            h = int(h_elem.text) if h_elem is not None and h_elem.text else 0
            if w > 0: current_w, current_h, current_ps = w, h, get_ps_by_dims(w, h)
            elem.clear()
        elif tag.endswith("Photo"):
            pid, ipath = elem.findtext('{*}Id'), elem.findtext('{*}ImagePath')
            if pid: photos.append(
                {"Id": int(pid), "ImagePath": ipath, "cols": current_w, "rows": current_h, "ps": current_ps})
            elem.clear()
        elif tag.endswith("TiePoint"):  #連接點與量測值
            meas = [[int(c.findtext('{*}PhotoId')), float(c.findtext('{*}x')), float(c.findtext('{*}y'))] for c in
                    elem.findall('{*}Measurement')]
            tps.append({"TP_id": str(tp_counter), "TP": meas})
            tp_counter += 1 #流水號
            elem.clear()
        elif tag.endswith("ControlPoint"):  #控制點提取
            name = elem.findtext('{*}Name')
            meas = [[int(c.findtext('{*}PhotoId')), float(c.findtext('{*}x')), float(c.findtext('{*}y'))] for c in
                    elem.findall('{*}Measurement')]
            cps.append({"TP_id_new": name.strip() if name else "CP", "TP": meas})    # 控制點直接存入 cps 列表，並直接指定最終的 ID 欄位名 "TP_id_new"
            elem.clear()    #記憶體管理要點，釋放已經處理過的 XML 節點物件
    return photos, tps, cps


# ==========================================
# 2. 選點模組 (加入補償機制與紀錄)
# ==========================================
def select_tie_points_optimized(photos, tps, pts_per_cell=2, buffer_ratio=0.05):
    """
    1. 加入 buffer_ratio：預設剔除邊緣 5% 區域的點。
    2. 權重排序：Visibility > Dist to Center。
    """
    print(f"執行優化選點與補償機制 (邊緣緩衝區: {buffer_ratio * 100}%)...")

    tp_visibility = {row['TP_id']: len(row['TP']) for row in tps}
    photo_to_tp_map = defaultdict(list)
    for row in tps:
        vis = tp_visibility[row['TP_id']]
        for mid, x, y in row['TP']:
            photo_to_tp_map[mid].append({"TP_id": row['TP_id'], "x": x, "y": y, "vis": vis})

    selected_global_ids = set()
    stats = []
    target_pts_per_image = pts_per_cell * 9  # 目標總點數 (預設18)

    for photo in photos:
        w, h = photo['cols'], photo['rows']
        if w == 0 or h == 0: continue

        # 邊緣緩衝定義
        bx, by = w * buffer_ratio, h * buffer_ratio
        cw, ch = w / 3, h / 3
        cell_centers = [((c + 0.5) * cw, (r + 0.5) * ch) for r in range(3) for c in range(3)]
        grid_bins = [[] for _ in range(9)]

        img_point_count = 0
        img_selected_tps = set()
        valid_points_in_img = []

        for pt in photo_to_tp_map[photo['Id']]:
            if not (bx < pt['x'] < w - bx and by < pt['y'] < h - by):
                continue

            c_idx, r_idx = min(int(pt['x'] // cw), 2), min(int(pt['y'] // ch), 2)
            idx = r_idx * 3 + c_idx
            pt['dist_sq'] = (pt['x'] - cell_centers[idx][0]) ** 2 + (pt['y'] - cell_centers[idx][1]) ** 2

            grid_bins[idx].append(pt)
            valid_points_in_img.append(pt)

        # 階段一：常規九宮格選點
        for bin_pts in grid_bins:
            bin_pts.sort(key=lambda p: (-p['vis'], p['dist_sq']))
            for p in bin_pts[:pts_per_cell]:
                selected_global_ids.add(p['TP_id'])
                img_selected_tps.add(p['TP_id'])
                img_point_count += 1

        # 階段二：補償機制
        compensated_pts = 0  # 紀錄這張圖補了幾點
        if img_point_count < target_pts_per_image:
            deficit = target_pts_per_image - img_point_count
            candidate_pts = [p for p in valid_points_in_img if p['TP_id'] not in img_selected_tps]
            candidate_pts.sort(key=lambda p: -p['vis'])

            for p in candidate_pts[:deficit]:
                selected_global_ids.add(p['TP_id'])
                img_selected_tps.add(p['TP_id'])
                img_point_count += 1
                compensated_pts += 1  # 累加補點數量

        # 記錄統計資訊，加入補點數量
        stats.append({
            "Image": Path(photo['ImagePath']).name,
            "Points": img_point_count,
            "Compensated": compensated_pts
        })

    return selected_global_ids, stats


# ==========================================
# 3. 輸出模組
# ==========================================
def export_ipf_files(photos, final_pts, out_dir, default_ps=0.0039):
    os.makedirs(out_dir, exist_ok=True)
    # 使用字典依序加入點位，先加入的會在前面 (保留控制點在前的順序)
    photo_data = defaultdict(list)
    for row in final_pts:
        for mid, x, y in row['TP']:
            photo_data[mid].append([str(row['TP_id_new']), x, y])

    for r in photos:
        ps = r.get("ps") or default_ps
        cols, rows = r["cols"], r["rows"]
        tps_in_photo = photo_data.get(r["Id"], [])

        if not tps_in_photo: continue

        out_path = Path(out_dir) / f"{Path(r['ImagePath']).stem}.ipf"
        header = ["IMAGE POINT FILE", str(len(tps_in_photo)),
                  "pt_id,val,fid_val,no_obs,l.,s.,sig_l,sig_s,res_l,res_s,fid_x,fid_y"]

        blocks = []
        for tid, x, y in tps_in_photo:
            xp, yp = ps * (x - 0.5 * (1 + cols)), ps * (0.5 * (1 + rows) - y)
            block = f"{tid} 1 1 1\n{(-yp / ps):.6f} {(xp / ps):.6f}\n0.000000 0.000000\n0.000000 0.000000\n{xp:.6f} {yp:.6f}"
            blocks.append(block)

        full_text = "\n".join(header) + "\n" + "\n\n".join(blocks)
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(full_text + "\n")


# ==========================================
# 主程式執行區 (直接執行)
# ==========================================
t_start = time.time()

photos_list, tps_list, cps_list = parse_metashape_xml(XML_INPUT)

if photos_list:
    # 這裡會自動執行補償機制、安全邊界限制，剔除影像邊緣 5% 範圍內的點位，降低畸變影響。
    selected_ids, stats_list = select_tie_points_optimized(photos_list, tps_list, pts_per_cell=2, buffer_ratio=0.05)

    tps_final_list = [tp for tp in tps_list if tp['TP_id'] in selected_ids]

    # 流水號重編
    z_len = len(str(len(tps_final_list)))
    for i, tp in enumerate(tps_final_list):
        tp['TP_id_new'] = str(i + 1).zfill(z_len)

    # 輸出 IPF
    final_pts_to_export = cps_list + tps_final_list
    export_ipf_files(photos_list, final_pts_to_export, OUT_FOLDER)

    # 輸出報告
    df_stats = pd.DataFrame(stats_list)
    avg_points = df_stats['Points'].mean() if not df_stats.empty else 0

    # 顯示統計摘要
    print("\n=== 選點分佈與補點摘要 ===")
    print(f"平均選點數: {avg_points:.1f} 點")

    if not df_stats.empty:
        print(f"最低點數影像: {df_stats['Points'].min()} 點")

        # 篩選出有觸發補點的影像
        comp_df = df_stats[df_stats['Compensated'] > 0]
        if not comp_df.empty:
            print(f"\n【觸發補點機制影像清單】 (共 {len(comp_df)} 張)")
            for _, row in comp_df.iterrows():
                # 印出：檔名、補了幾點、最後總點數
                print(f"  > {row['Image']}: 自動補足 {row['Compensated']} 點 (最終: {row['Points']} 點)")
        else:
            print("\n【觸發補點機制影像清單】")
            print("  > 表現優良！無影像需要補點，所有影像常規選點皆滿 18 點。")

    print(f"\n總處理耗時: {time.time() - t_start:.2f} 秒")
