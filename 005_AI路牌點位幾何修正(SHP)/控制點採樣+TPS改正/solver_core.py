"""
solver_core.py
核心求解器：全域薄板樣條函數 (TPS) 幾何校正
使用 scipy.interpolate.RBFInterpolator（thin_plate_spline）
"""

import numpy as np
from scipy.interpolate import RBFInterpolator
from shapely.geometry import Point, MultiPoint
import geopandas as gpd


class SolverCore:
    """
    全域 TPS 幾何轉換求解器。

    以所有控制點一次擬合全測區變形場，
    並以 Leave-One-Out 交叉驗證計算真實殘差。
    """

    def solve(self, pairs: list[dict]) -> tuple[dict, list[dict], dict]:
        """
        擬合全域 TPS 模型。

        Args:
            pairs: 全測區所有控制點配對
                   每個元素含 'manual_xy' 與 'ai_xy'

        Returns:
            params    : {'model_x', 'model_y', 'type', 'src_pts', 'tar_pts'}
            residuals : LOO 殘差列表
            rmse      : {'x', 'y', 'total'}
        """
        n = len(pairs)
        if n < 6:
            raise ValueError(
                f"TPS 至少需要 6 組控制點，目前只有 {n} 組。"
                f"請增加控制點或改用四參數模式。"
            )

        src_x = np.array([p["ai_xy"][0] for p in pairs])
        src_y = np.array([p["ai_xy"][1] for p in pairs])
        tar_x = np.array([p["manual_xy"][0] for p in pairs])
        tar_y = np.array([p["manual_xy"][1] for p in pairs])

        src_pts = np.column_stack([src_x, src_y])

        # ── 全域 TPS 擬合 ────────────────────────────────────────────
        model_x = RBFInterpolator(src_pts, tar_x, kernel="thin_plate_spline", degree=1)
        model_y = RBFInterpolator(src_pts, tar_y, kernel="thin_plate_spline", degree=1)

        # ── LOO 殘差（真實泛化誤差）──────────────────────────────────
        residuals = self._loo_residuals(src_x, src_y, tar_x, tar_y, pairs)
        rmse      = self._calc_rmse(residuals)

        params = {
            "type":    "TPS",
            "model_x": model_x,
            "model_y": model_y,
            "src_pts": src_pts,   # 保留原始控制點，供凸包計算使用
            "tar_pts": np.column_stack([tar_x, tar_y]),
        }

        return params, residuals, rmse

    def apply_transform(self, ai_gdf: gpd.GeoDataFrame,
                        params: dict) -> gpd.GeoDataFrame:
        """
        套用 TPS 轉換至整個 GeoDataFrame。
        在控制點凸包外的點標記 corrected=False，座標維持原值。

        Args:
            ai_gdf : 待校正的 AI 點 GeoDataFrame
            params : solve() 輸出的參數字典

        Returns:
            校正後的 GeoDataFrame，含 corrected 與 warn_msg 欄位
        """
        model_x  = params["model_x"]
        model_y  = params["model_y"]
        src_pts  = params["src_pts"]

        # 建立控制點凸包
        hull = MultiPoint(src_pts).convex_hull

        orig_x = ai_gdf.geometry.x.to_numpy()
        orig_y = ai_gdf.geometry.y.to_numpy()
        has_z  = ai_gdf.geometry.has_z.any()
        orig_z = ai_gdf.geometry.z.to_numpy() if has_z else None

        # TPS 批次計算（全部點一次送入，效率高）
        query_pts  = np.column_stack([orig_x, orig_y])
        new_x_all  = model_x(query_pts)
        new_y_all  = model_y(query_pts)

        new_geoms   = []
        corrected   = []
        warn_msgs   = []

        for i, (ox, oy) in enumerate(zip(orig_x, orig_y)):
            pt_geom = Point(ox, oy)
            in_hull = hull.contains(pt_geom)

            if in_hull:
                nx, ny = new_x_all[i], new_y_all[i]
                new_geoms.append(Point(nx, ny, orig_z[i]) if has_z else Point(nx, ny))
                corrected.append(True)
                warn_msgs.append("")
            else:
                # 凸包外：保留原始座標，標記警示
                new_geoms.append(pt_geom if not has_z else Point(ox, oy, orig_z[i]))
                corrected.append(False)
                warn_msgs.append("OUTSIDE_HULL")

        result = ai_gdf.copy()
        result["geometry"]  = new_geoms
        result["corrected"] = corrected
        result["warn_msg"]  = warn_msgs

        outside_count = warn_msgs.count("OUTSIDE_HULL")
        if outside_count > 0:
            print(f"    [警告] {outside_count} 個點位於控制點凸包外，"
                  f"座標維持原值（corrected=False）")

        return result

    # ─── 私有方法 ────────────────────────────────────────────────────

    def _loo_residuals(self, src_x, src_y, tar_x, tar_y,
                       pairs: list[dict]) -> list[dict]:
        """
        Leave-One-Out 交叉驗證殘差。
        每次排除一個控制點，用其餘點擬合 TPS，預測被排除點。
        """
        n = len(src_x)
        residuals = []

        for i in range(n):
            mask = np.ones(n, dtype=bool)
            mask[i] = False

            src_loo = np.column_stack([src_x[mask], src_y[mask]])
            try:
                m_x = RBFInterpolator(src_loo, tar_x[mask],
                                      kernel="thin_plate_spline", degree=1)
                m_y = RBFInterpolator(src_loo, tar_y[mask],
                                      kernel="thin_plate_spline", degree=1)
                query = np.array([[src_x[i], src_y[i]]])
                pred_x = float(m_x(query))
                pred_y = float(m_y(query))
            except Exception:
                # LOO 點數不足時退化為原座標
                pred_x, pred_y = src_x[i], src_y[i]

            dx   = pred_x - tar_x[i]
            dy   = pred_y - tar_y[i]
            dist = np.sqrt(dx**2 + dy**2)

            residuals.append({
                "manual_xy": pairs[i]["manual_xy"],
                "ai_xy":     pairs[i]["ai_xy"],
                "pred_xy":   (pred_x, pred_y),
                "dx": dx, "dy": dy, "dist": dist
            })

        return residuals

    def _calc_rmse(self, residuals: list[dict]) -> dict:
        rmse_x     = np.sqrt(np.mean([r["dx"]**2   for r in residuals]))
        rmse_y     = np.sqrt(np.mean([r["dy"]**2   for r in residuals]))
        rmse_total = np.sqrt(np.mean([r["dist"]**2 for r in residuals]))
        return {"x": rmse_x, "y": rmse_y, "total": rmse_total}
