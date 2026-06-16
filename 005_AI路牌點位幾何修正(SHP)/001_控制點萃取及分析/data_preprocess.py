"""
data_preprocess.py
控制點收集與配對前處理
- PT 欄位名稱可變參數（預設 "PT"）
- 偵測到 PT 欄位時詢問是否作為配對編號
- 無 PT 欄位直接執行自動模式
- PT 模式後可選擇兩階段補點：
    第一輪：孤立點篩選（_match_auto）
    第二輪：Voronoi 最大空隙（_match_voronoi_supplement）
    兩輪共用停止條件（候選點用完 / 分佈已均勻）
"""

import numpy as np
import geopandas as gpd
from shapely.geometry import MultiPoint, Point
from shapely.ops import voronoi_diagram


class DataPreprocessor:

    def __init__(self, ai_gdf: gpd.GeoDataFrame, manual_gdf: gpd.GeoDataFrame,
                 max_match_dist: float = 3.0, isolation_dist: float = 2.0,
                 roi_field: str = "ROI", pt_field: str = "PT",
                 voronoi_stop_ratio: float = 2.0,
                 survey_area: float = None):
        self.ai_gdf             = ai_gdf.copy()
        self.manual_gdf         = manual_gdf.copy()
        self.max_match_dist     = max_match_dist
        self.isolation_dist     = isolation_dist
        self.roi_field          = roi_field
        self.pt_field           = pt_field
        self.voronoi_stop_ratio = voronoi_stop_ratio
        self.survey_area        = survey_area  # 實際測區面積（m²），None 時改用 AI 點凸包

    # ─── 公開方法 ────────────────────────────────────────────────────

    def build_control_pairs(self) -> tuple[list[dict], int, list[dict]]:
        """
        主流程：
        1. 偵測 PT 欄位 → 詢問是否作為配對編號
        2. PT 模式 or 自動模式
        3. PT 模式後詢問是否補點（兩階段補點）

        Returns:
            pairs     : 最終控制點配對列表
            count     : 配對數量
            supp_log  : 補點記錄列表（未補點時為空 list）
        """
        ai_has_pt     = self._has_pt_field(self.ai_gdf)
        manual_has_pt = self._has_pt_field(self.manual_gdf)
        use_pt        = False
        supp_log      = []

        # ── PT 欄位偵測 ───────────────────────────────────────────────
        if ai_has_pt or manual_has_pt:
            sides = []
            if ai_has_pt:     sides.append("AI")
            if manual_has_pt: sides.append("人工")
            print(f"\n  [偵測] {' 與 '.join(sides)} SHP 含有 "
                  f"'{self.pt_field}' 欄位且有值。")

            if ai_has_pt and manual_has_pt:
                ans = input(f"  是否將 '{self.pt_field}' 欄位作為控制點配對編號？(Y/N): ").strip().upper()
                use_pt = (ans == "Y")
            else:
                missing = "人工" if ai_has_pt else "AI"
                print(f"  [警告] 僅單邊有 '{self.pt_field}' 值（{missing} 側缺少），"
                      f"無法使用 PT 模式，改為自動配對。")

        # ── 執行配對 ──────────────────────────────────────────────────
        if use_pt:
            pairs = self._match_by_pt(self.ai_gdf, self.manual_gdf)
            pairs = self._assign_match_id(pairs)
            print(f"  PT 欄位配對完成，共 {len(pairs)} 組")
            pairs = self._prompt_supplement(pairs, supp_log)
        else:
            pairs = self._match_auto(self.ai_gdf, self.manual_gdf,
                                     used_ai_idx=set(), used_man_idx=set())
            pairs = self._assign_match_id(pairs)
            print(f"  自動配對完成，共 {len(pairs)} 組")

        self._print_distribution_summary(pairs)
        return pairs, len(pairs), supp_log

    def add_pt_field(self, ai_path: str, manual_path: str):
        """在兩個 SHP 中新增空白 PT 欄位並儲存。"""
        for path, gdf in [(ai_path, self.ai_gdf),
                          (manual_path, self.manual_gdf)]:
            if self.pt_field not in gdf.columns:
                gdf[self.pt_field] = None
            gdf.to_file(path)
            print(f"  已更新 '{self.pt_field}' 欄位：{path}")

    # ─── PT 模式後補點 ────────────────────────────────────────────────

    def _prompt_supplement(self, pairs: list[dict],
                            supp_log: list[dict]) -> list[dict]:
        """
        PT 配對後兩階段迭代補點：
          第一輪：孤立點篩選（批次配對）
          第二輪：Voronoi 迭代補點
            每次迭代：
              1. 計算 Voronoi，找最大 cell
              2. 全域剩餘孤立點篩選
              3. 排序：最大 cell 內優先，其餘依原順序
              4. 批次配對（雙向一對一去重）
            停止條件：分佈已均勻 or 候選人工點用完
        supp_log 補點記錄 append 進去。
        """
        ans = input("  是否繼續以自動模式補充剩餘控制點？(Y/N): ").strip().upper()
        if ans != "Y":
            return pairs

        used_ai_idx  = {p["ai_idx"]     for p in pairs}
        used_man_idx = {p["manual_idx"] for p in pairs}
        all_new      = []

        # ── 第一輪：孤立點篩選（批次） ───────────────────────────────
        print("  [補點第一輪] 孤立點篩選...")
        round1 = self._match_auto(
            self.ai_gdf, self.manual_gdf, used_ai_idx, used_man_idx
        )
        if round1:
            for p in round1:
                used_ai_idx.add(p["ai_idx"])
                used_man_idx.add(p["manual_idx"])
                supp_log.append({**p, "iter": 0, "round": 1,
                                  "method": "孤立點篩選"})
            all_new.extend(round1)
            print(f"    孤立點補入 {len(round1)} 組")
        else:
            print("    無孤立點候選")

        # 第一輪後均勻度檢查
        current_pairs = pairs + all_new
        if self._is_distribution_uniform(current_pairs):
            print("  [補點停止] 第一輪後分佈已均勻，略過第二輪")
            return self._assign_match_id(current_pairs)

        # ── 第二輪：Voronoi 迭代 ──────────────────────────────────────
        print("  [補點第二輪] Voronoi 迭代補點...")
        iter_count = 0
        while True:
            iter_count += 1
            remaining_man = self.manual_gdf[
                ~self.manual_gdf.index.isin(used_man_idx)
            ]

            # 停止條件：候選人工點用完
            if len(remaining_man) == 0:
                print(f"    [停止] 第 {iter_count} 輪：候選人工點已全數配對")
                break

            # 停止條件：分佈已均勻
            current_pairs = pairs + all_new
            if self._is_distribution_uniform(current_pairs):
                print(f"    [停止] 第 {iter_count} 輪：分佈已均勻")
                break

            # 計算 Voronoi，找最大 cell
            survey_hull  = self._get_survey_hull()
            ctrl_coords  = [p["manual_xy"] for p in current_pairs]
            cells_sorted = self._get_cells_sorted(ctrl_coords, survey_hull)
            largest_cell = cells_sorted[0] if cells_sorted else None

            # 全域剩餘孤立點篩選
            isolated = self._filter_isolated_manual(remaining_man)
            if len(isolated) == 0:
                print(f"    [停止] 第 {iter_count} 輪：無孤立候選點")
                break

            # 排序：最大 cell 內優先
            if largest_cell is not None:
                in_cell  = [idx for idx, row in isolated.iterrows()
                            if largest_cell.contains(
                                Point(row.geometry.x, row.geometry.y))]
                out_cell = [idx for idx in isolated.index if idx not in in_cell]
                sorted_idx = in_cell + out_cell
                isolated   = isolated.loc[sorted_idx]

            # 批次配對
            avail_ai   = self.ai_gdf[~self.ai_gdf.index.isin(used_ai_idx)]
            candidates = []
            for man_idx, man_row in isolated.iterrows():
                mx, my = man_row.geometry.x, man_row.geometry.y
                if len(avail_ai) == 0:
                    break
                best_idx, best_dist = self._find_nearest(mx, my, avail_ai)
                if best_dist <= self.max_match_dist:
                    ar = avail_ai.loc[best_idx]
                    candidates.append({
                        "manual_xy":  (mx, my),
                        "ai_xy":      (ar.geometry.x, ar.geometry.y),
                        "ai_idx":     best_idx,
                        "manual_idx": man_idx,
                        "dist":       best_dist
                    })

            if not candidates:
                print(f"    [停止] 第 {iter_count} 輪：無可配對候選點（超出距離閾值）")
                break

            # 雙向一對一去重
            best_by_ai = {}
            for c in candidates:
                idx = c["ai_idx"]
                if idx not in best_by_ai or c["dist"] < best_by_ai[idx]["dist"]:
                    best_by_ai[idx] = c

            best_by_manual = {}
            for c in best_by_ai.values():
                key = c["manual_xy"]
                if key not in best_by_manual or c["dist"] < best_by_manual[key]["dist"]:
                    best_by_manual[key] = c

            new_this_iter = list(best_by_manual.values())

            for p in new_this_iter:
                used_ai_idx.add(p["ai_idx"])
                used_man_idx.add(p["manual_idx"])
                supp_log.append({**p, "iter": iter_count, "round": 2,
                                  "method": "Voronoi迭代"})
            all_new.extend(new_this_iter)
            print(f"    第 {iter_count} 輪補入 {len(new_this_iter)} 組")

        # 最終統計
        r1 = sum(1 for s in supp_log if s.get("round") == 1)
        r2 = sum(1 for s in supp_log if s.get("round") == 2)
        pt = len(pairs)
        if all_new:
            final = self._assign_match_id(pairs + all_new)
            total = len(final)
            print(f"  補點完成：PT配對 {pt} 組 + 孤立點 {r1} 組 + Voronoi迭代 {r2} 組"
                  f"，總計 {total} 組")
            return final
        else:
            print("  無可補充的候選點")
            return pairs

    def _is_distribution_uniform(self, pairs: list[dict]) -> bool:
        """
        檢查目前控制點分佈是否已達均勻標準。
        基準面積優先使用 survey_area（實際測區面積），否則用控制點凸包。
        最大 Voronoi cell < 基準面積 / 控制點數 × voronoi_stop_ratio → 均勻
        """
        if len(pairs) < 2:
            return False
        coords = [p["manual_xy"] for p in pairs]
        if self.survey_area and self.survey_area > 0:
            base_area = self.survey_area
            envelope  = MultiPoint([Point(x, y) for x, y in coords]).convex_hull
        else:
            envelope  = MultiPoint([Point(x, y) for x, y in coords]).convex_hull
            base_area = envelope.area
        threshold = (base_area / len(pairs)) * self.voronoi_stop_ratio
        max_area  = self._max_voronoi_cell_area(coords, envelope)
        return max_area < threshold

    def _get_survey_hull(self):
        """回傳測區 envelope（AI 點凸包）。"""
        pts = [(r.geometry.x, r.geometry.y) for _, r in self.ai_gdf.iterrows()]
        return MultiPoint(pts).convex_hull

    def get_sparse_roi_report(self, pairs: list[dict],
                               survey_gdf: gpd.GeoDataFrame) -> list[dict]:
        """
        分析各 ROI 的控制點密度，回傳稀疏 ROI 清單。
        判斷標準：
          1. 最大 Voronoi cell 所在的 ROI
          2. ROI 控制點密度低於全域平均
        兩個條件各自獨立標記。

        Args:
            pairs      : 最終控制點配對列表
            survey_gdf : 測區面資料 GeoDataFrame（含 roi_field 欄位）

        Returns:
            list[dict]，每個 ROI 一筆：
            { roi_id, ctrl_count, roi_area, density,
              sparse_by_voronoi, sparse_by_density }
        """
        if len(pairs) < 2 or survey_gdf is None:
            return []

        survey_hull = self._get_survey_hull()
        ctrl_coords = [p["manual_xy"] for p in pairs]

        # 計算各控制點所屬 ROI
        def point_roi(xy):
            pt = Point(xy)
            for _, row in survey_gdf.iterrows():
                if row.geometry.contains(pt):
                    return str(row[self.roi_field])
            return "UNKNOWN"

        # ROI 控制點計數
        roi_counts = {}
        for p in pairs:
            roi = point_roi(p["manual_xy"])
            roi_counts[roi] = roi_counts.get(roi, 0) + 1

        # ROI 面積
        roi_areas = {}
        for _, row in survey_gdf.iterrows():
            roi_id = str(row[self.roi_field])
            roi_areas[roi_id] = row.geometry.area

        # 全域平均密度（控制點數 / 總面積）
        total_area   = sum(roi_areas.values()) or 1
        global_density = len(pairs) / total_area

        # 找最大 Voronoi cell 所在 ROI
        cells_sorted   = self._get_cells_sorted(ctrl_coords, survey_hull)
        largest_cell   = cells_sorted[0] if cells_sorted else None
        largest_center = largest_cell.centroid if largest_cell else None
        largest_roi    = point_roi((largest_center.x, largest_center.y)) \
                         if largest_center else "UNKNOWN"

        # 組合報告
        report = []
        all_roi_ids = set(roi_areas.keys()) | set(roi_counts.keys())
        for roi_id in sorted(all_roi_ids):
            count   = roi_counts.get(roi_id, 0)
            area    = roi_areas.get(roi_id, 0)
            density = count / area if area > 0 else 0
            report.append({
                "ROI":              roi_id,
                "控制點數":         count,
                "ROI面積_m2":       round(area, 1),
                "密度_點每萬m2":    round(density * 10000, 4),
                "最大cell所在ROI":  roi_id == largest_roi,
                "密度低於全域平均": density < global_density,
            })

        return report

    def _get_cells_sorted(self, ctrl_coords: list, envelope) -> list:
        """回傳 Voronoi cell 幾何（與 envelope 取交集），由大到小排列。"""
        if len(ctrl_coords) < 2:
            return [envelope]
        try:
            pts     = MultiPoint([Point(x, y) for x, y in ctrl_coords])
            regions = voronoi_diagram(pts, envelope=envelope)
            clipped = [r.intersection(envelope) for r in regions.geoms]
            clipped = [c for c in clipped if not c.is_empty]
            return sorted(clipped, key=lambda c: c.area, reverse=True)
        except Exception:
            return []

    def _candidates_in_cell(self, cell_geom,
                             remaining_man: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """回傳落在 cell 內的候選人工點。"""
        idx_in = [idx for idx, row in remaining_man.iterrows()
                  if cell_geom.contains(Point(row.geometry.x, row.geometry.y))]
        return remaining_man.loc[idx_in]

    def _max_voronoi_cell_area(self, ctrl_coords: list, envelope) -> float:
        """計算目前控制點 Voronoi 圖中最大 cell 的面積。"""
        if len(ctrl_coords) < 2:
            return float("inf")
        try:
            pts     = MultiPoint([Point(x, y) for x, y in ctrl_coords])
            regions = voronoi_diagram(pts, envelope=envelope)
            clipped = [r.intersection(envelope) for r in regions.geoms]
            areas   = [r.area for r in clipped if not r.is_empty]
            return max(areas) if areas else float("inf")
        except Exception:
            return float("inf")

    # ─── 自動配對 ────────────────────────────────────────────────────

    def _match_auto(self, ai_gdf: gpd.GeoDataFrame,
                    manual_gdf: gpd.GeoDataFrame,
                    used_ai_idx: set, used_man_idx: set) -> list[dict]:
        avail_man = manual_gdf[~manual_gdf.index.isin(used_man_idx)]
        avail_ai  = ai_gdf[~ai_gdf.index.isin(used_ai_idx)]

        isolated = self._filter_isolated_manual(avail_man)
        if len(isolated) == 0:
            return []

        candidates = []
        for man_idx, man_row in isolated.iterrows():
            mx, my = man_row.geometry.x, man_row.geometry.y
            best_idx, best_dist = self._find_nearest(mx, my, avail_ai)
            if best_dist <= self.max_match_dist:
                ar = avail_ai.loc[best_idx]
                candidates.append({
                    "manual_xy":  (mx, my),
                    "ai_xy":      (ar.geometry.x, ar.geometry.y),
                    "ai_idx":     best_idx,
                    "manual_idx": man_idx,
                    "dist":       best_dist
                })

        best_by_ai = {}
        for c in candidates:
            idx = c["ai_idx"]
            if idx not in best_by_ai or c["dist"] < best_by_ai[idx]["dist"]:
                best_by_ai[idx] = c

        best_by_manual = {}
        for c in best_by_ai.values():
            key = c["manual_xy"]
            if key not in best_by_manual or c["dist"] < best_by_manual[key]["dist"]:
                best_by_manual[key] = c

        pairs = list(best_by_manual.values())

        dup_removed = len(candidates) - len(pairs)
        if dup_removed > 0:
            print(f"    [配對去重] 移除 {dup_removed} 組重複配對，剩餘 {len(pairs)} 組")

        return pairs

    # ─── PT 模式 ─────────────────────────────────────────────────────

    def _match_by_pt(self, ai_gdf: gpd.GeoDataFrame,
                     manual_gdf: gpd.GeoDataFrame) -> list[dict]:
        pairs      = []
        ai_has_pt  = ai_gdf[ai_gdf[self.pt_field].notna()]
        man_has_pt = manual_gdf[manual_gdf[self.pt_field].notna()]

        ai_by_pt  = {row[self.pt_field]: idx for idx, row in ai_has_pt.iterrows()}
        man_by_pt = {row[self.pt_field]: idx for idx, row in man_has_pt.iterrows()}
        common    = set(ai_by_pt.keys()) & set(man_by_pt.keys())

        for pt_id in common:
            ai_idx  = ai_by_pt[pt_id]
            man_idx = man_by_pt[pt_id]
            ar = ai_gdf.loc[ai_idx]
            mr = manual_gdf.loc[man_idx]
            pairs.append({
                "manual_xy":  (mr.geometry.x, mr.geometry.y),
                "ai_xy":      (ar.geometry.x, ar.geometry.y),
                "ai_idx":     ai_idx,
                "manual_idx": man_idx,
                "pt_id":      pt_id,
                "dist":       0.0
            })
        return pairs

    # ─── 工具方法 ────────────────────────────────────────────────────

    def _has_pt_field(self, gdf: gpd.GeoDataFrame) -> bool:
        return (self.pt_field in gdf.columns and
                gdf[self.pt_field].notna().any())

    def _filter_isolated_manual(self,
                                 manual_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        coords = np.array([(r.geometry.x, r.geometry.y)
                           for _, r in manual_gdf.iterrows()])
        if len(coords) == 0:
            return manual_gdf.iloc[0:0]
        isolated_idx = []
        for i, (xi, yi) in enumerate(coords):
            dists    = np.sqrt(((coords - [xi, yi])**2).sum(axis=1))
            dists[i] = np.inf
            if dists.min() > self.isolation_dist:
                isolated_idx.append(manual_gdf.index[i])
        return manual_gdf.loc[isolated_idx]

    def _find_nearest(self, x: float, y: float,
                      gdf: gpd.GeoDataFrame) -> tuple[int, float]:
        best_idx, best_dist = None, np.inf
        for idx, row in gdf.iterrows():
            d = np.sqrt((row.geometry.x - x)**2 + (row.geometry.y - y)**2)
            if d < best_dist:
                best_dist, best_idx = d, idx
        return best_idx, best_dist

    def _assign_match_id(self, pairs: list[dict]) -> list[dict]:
        for i, pair in enumerate(pairs, start=1):
            pair["match_id"] = i
        return pairs

    def _print_distribution_summary(self, pairs: list[dict]):
        """印出控制點空間分佈摘要。"""
        if len(pairs) < 2:
            return
        coords   = [p["manual_xy"] for p in pairs]
        envelope = MultiPoint([Point(x, y) for x, y in coords]).convex_hull
        base_area = self.survey_area if (self.survey_area and self.survey_area > 0) \
                    else envelope.area
        avg_area  = base_area / len(pairs)
        max_area  = self._max_voronoi_cell_area(coords, envelope)
        ratio     = max_area / avg_area if avg_area > 0 else 0
        src       = "實際測區面積" if (self.survey_area and self.survey_area > 0) \
                    else "控制點凸包"

        print(f"\n  [分佈摘要] 控制點數：{len(pairs)}")
        print(f"             基準面積（{src}）：{base_area:.1f} m²")
        print(f"             平均負責面積：{avg_area:.1f} m²")
        print(f"             最大 Voronoi cell：{max_area:.1f} m²"
              f"  (平均的 {ratio:.1f} 倍)")
        if ratio > self.voronoi_stop_ratio:
            print(f"  [警告] 最大 cell 超過平均 {self.voronoi_stop_ratio} 倍，"
                  f"建議在稀疏區域補充控制點")