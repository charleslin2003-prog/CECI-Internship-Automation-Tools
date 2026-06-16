"""
data_preprocess.py
負責：全測區控制點收集、空間鄰近過濾、PT 欄位解析
（TPS 版本：不再依 ROI 分區，改為全測區統一處理）
"""

import numpy as np
import geopandas as gpd


class DataPreprocessor:
    """
    全測區控制點配對前處理模組。

    支援兩種配對模式：
    1. 自動篩選模式：篩選孤立人工點 → 最近鄰配對 AI 點
    2. PT 欄位模式：PT 欄位有值時，以相同編號強制配對
    """

    def __init__(self, ai_gdf: gpd.GeoDataFrame, manual_gdf: gpd.GeoDataFrame,
                 max_match_dist: float = 3.0, isolation_dist: float = 2.0,
                 roi_field: str = "ROI"):
        self.ai_gdf         = ai_gdf.copy()
        self.manual_gdf     = manual_gdf.copy()
        self.max_match_dist = max_match_dist
        self.isolation_dist = isolation_dist
        self.roi_field      = roi_field

    # ─── 公開方法 ────────────────────────────────────────────────────

    def build_control_pairs(self) -> tuple[list[dict], int]:
        """
        在全測區收集所有控制點配對（不分 ROI）。

        Returns:
            pairs      : 全測區配對列表
            auto_count : 自動配對數量（PT 模式為 0）
        """
        # 優先使用 PT 欄位配對
        if (self._has_pt_field(self.ai_gdf) and
                self._has_pt_field(self.manual_gdf)):
            pairs = self._match_by_pt(self.ai_gdf, self.manual_gdf)
            pairs = self._assign_match_id(pairs)
            print(f"  使用 PT 欄位配對，找到 {len(pairs)} 組控制點")
            return pairs, 0

        # 自動配對
        pairs = self._match_auto(self.ai_gdf, self.manual_gdf)
        pairs = self._assign_match_id(pairs)
        print(f"  自動配對，找到 {len(pairs)} 組控制點")
        return pairs, len(pairs)

    def build_roi_line_pairs(self, pairs: list[dict]) -> dict[str, list[dict]]:
        """
        將全域配對結果依 ROI 重新分組，供連線 SHP 輸出使用。
        透過空間查詢找到每組配對所屬的 ROI。

        Returns:
            { roi_id: [ pair, ... ] }
        """
        roi_pairs = {}

        if self.roi_field not in self.manual_gdf.columns:
            roi_pairs["ALL"] = pairs
            return roi_pairs

        for pair in pairs:
            mx, my = pair["manual_xy"]
            # 找距離最近的人工點取其 ROI 值
            roi_val = self._find_roi_of_point(mx, my)
            roi_pairs.setdefault(roi_val, []).append(pair)

        return roi_pairs

    def add_pt_field(self, ai_path: str, manual_path: str):
        """在兩個 SHP 中新增空白 PT 欄位並儲存。"""
        for path, gdf in [(ai_path, self.ai_gdf),
                          (manual_path, self.manual_gdf)]:
            if "PT" not in gdf.columns:
                gdf["PT"] = None
            gdf.to_file(path)
            print(f"  已更新 PT 欄位：{path}")

    # ─── 私有方法 ────────────────────────────────────────────────────

    def _has_pt_field(self, gdf: gpd.GeoDataFrame) -> bool:
        return "PT" in gdf.columns and gdf["PT"].notna().any()

    def _match_by_pt(self, ai_gdf: gpd.GeoDataFrame,
                     manual_gdf: gpd.GeoDataFrame) -> list[dict]:
        pairs      = []
        ai_has_pt  = ai_gdf[ai_gdf["PT"].notna()]
        man_has_pt = manual_gdf[manual_gdf["PT"].notna()]

        # 用 PT 值建立查找表，保留原始 DataFrame index
        ai_by_pt  = {row["PT"]: idx for idx, row in ai_has_pt.iterrows()}
        man_by_pt = {row["PT"]: idx for idx, row in man_has_pt.iterrows()}
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

    def _match_auto(self, ai_gdf: gpd.GeoDataFrame,
                    manual_gdf: gpd.GeoDataFrame) -> list[dict]:
        isolated = self._filter_isolated_manual(manual_gdf)
        if len(isolated) == 0:
            return []

        # 第一輪：收集所有候選配對
        candidates = []
        for man_idx, man_row in isolated.iterrows():
            mx, my = man_row.geometry.x, man_row.geometry.y
            best_idx, best_dist = self._find_nearest(mx, my, ai_gdf)

            if best_dist <= self.max_match_dist:
                ar = ai_gdf.loc[best_idx]
                candidates.append({
                    "manual_xy":  (mx, my),
                    "ai_xy":      (ar.geometry.x, ar.geometry.y),
                    "ai_idx":     best_idx,
                    "manual_idx": man_idx,
                    "dist":       best_dist
                })

        # 第二輪：確保 AI 點一對一（同一 AI 點被多個人工點配到，只保留距離最近那筆）
        best_by_ai = {}
        for c in candidates:
            idx = c["ai_idx"]
            if idx not in best_by_ai or c["dist"] < best_by_ai[idx]["dist"]:
                best_by_ai[idx] = c

        # 同樣確保人工點一對一（同一人工點不重複出現）
        best_by_manual = {}
        for c in best_by_ai.values():
            key = c["manual_xy"]
            if key not in best_by_manual or c["dist"] < best_by_manual[key]["dist"]:
                best_by_manual[key] = c

        pairs = [
            {
                "manual_xy":  c["manual_xy"],
                "ai_xy":      c["ai_xy"],
                "ai_idx":     c["ai_idx"],
                "manual_idx": c.get("manual_idx"),
                "dist":       c["dist"]
            }
            for c in best_by_manual.values()
        ]

        dup_removed = len(candidates) - len(pairs)
        if dup_removed > 0:
            print(f"    [配對去重] 移除 {dup_removed} 組重複配對（共用點），剩餘 {len(pairs)} 組")

        return pairs

    def _filter_isolated_manual(self,
                                 manual_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        coords = np.array([(r.geometry.x, r.geometry.y)
                           for _, r in manual_gdf.iterrows()])
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
        """為每個配對加入全域唯一的 match_id（從 1 開始）。"""
        for i, pair in enumerate(pairs, start=1):
            pair["match_id"] = i
        return pairs

    def _find_roi_of_point(self, x: float, y: float) -> str:
        """找距離 (x,y) 最近的人工點，回傳其 ROI 值。"""
        best_roi, best_dist = "UNKNOWN", np.inf
        for _, row in self.manual_gdf.iterrows():
            d = np.sqrt((row.geometry.x - x)**2 + (row.geometry.y - y)**2)
            if d < best_dist:
                best_dist = d
                best_roi  = str(row.get(self.roi_field, "UNKNOWN"))
        return best_roi