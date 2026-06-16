"""
visualization_report.py
殘差散布圖 — TPS 全域版本
支援多 ROI 分色顯示於同一張散布圖
"""

import os
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from matplotlib.gridspec import GridSpec
from matplotlib.lines import Line2D

matplotlib.rcParams["font.family"] = ["Microsoft JhengHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False


class VisualizationReport:

    RMSE_WARNING_THRESHOLD = 0.05  # 5 cm

    def __init__(self, output_dir: str = "error_reports"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def plot_error_distribution(self, roi: str, pairs: list[dict],
                                residuals: list[dict], rmse: dict,
                                roi_pairs: dict = None):
        """
        繪製全域殘差散布圖。
        若傳入 roi_pairs，控制點依 ROI 分色顯示。

        Args:
            roi       : 圖表標題用（TPS 版固定為 'GLOBAL'）
            pairs     : 全域控制點配對列表
            residuals : LOO 殘差列表
            rmse      : {'x', 'y', 'total'}（單位：公尺）
            roi_pairs : { roi_id: [pair, ...] }，供分色使用
        """
        dx_cm        = [r["dx"]   * 100 for r in residuals]
        dy_cm        = [r["dy"]   * 100 for r in residuals]
        dist_cm      = [r["dist"] * 100 for r in residuals]
        rmse_x_cm    = rmse["x"]     * 100
        rmse_y_cm    = rmse["y"]     * 100
        rmse_tot_cm  = rmse["total"] * 100

        # ── 畫布 ────────────────────────────────────────────────────
        BG    = "#f7f9fc"
        PANEL = "#ffffff"
        TEXT  = "#1a1d23"
        GRID  = "#dde2ea"
        AMBER = "#f0a500"
        RED   = "#e84040"

        fig = plt.figure(figsize=(13, 7), facecolor=BG)
        gs  = GridSpec(2, 2, figure=fig,
                       left=0.08, right=0.95, top=0.86, bottom=0.10,
                       hspace=0.45, wspace=0.35)

        ax_main   = fig.add_subplot(gs[:, 0])
        ax_hist_x = fig.add_subplot(gs[0, 1])
        ax_hist_y = fig.add_subplot(gs[1, 1])

        for ax in [ax_main, ax_hist_x, ax_hist_y]:
            ax.set_facecolor(PANEL)
            ax.tick_params(colors=TEXT, labelsize=8)
            for spine in ax.spines.values():
                spine.set_edgecolor(GRID)

        # ── 主圖：殘差散布，依 ROI 分色 ─────────────────────────────
        if roi_pairs:
            roi_ids  = sorted(roi_pairs.keys())
            cmap_roi = cm.get_cmap("tab10", max(len(roi_ids), 1))
            roi_color_map = {r: cmap_roi(i) for i, r in enumerate(roi_ids)}

            # 建立每個 pair → residual 的對應（用 ai_xy 作 key）
            res_by_ai = {r["ai_xy"]: r for r in residuals}

            legend_handles = []
            for roi_id, rp in roi_pairs.items():
                xs, ys = [], []
                for pair in rp:
                    res = res_by_ai.get(pair["ai_xy"])
                    if res:
                        xs.append(res["dx"] * 100)
                        ys.append(res["dy"] * 100)
                color = roi_color_map[roi_id]
                ax_main.scatter(xs, ys, color=color, s=65, zorder=5,
                                edgecolors="#555", linewidths=0.5, label=roi_id)
                legend_handles.append(
                    Line2D([0], [0], marker="o", color="w",
                           markerfacecolor=color, markersize=7, label=roi_id)
                )
            ax_main.legend(handles=legend_handles, fontsize=7,
                           loc="upper right", framealpha=0.7)
        else:
            # 無 ROI 資訊，用殘差距離著色
            max_d = max(dist_cm) if max(dist_cm) > 0 else 0.01
            norm  = matplotlib.colors.Normalize(vmin=0, vmax=max_d)
            sc    = ax_main.scatter(dx_cm, dy_cm, c=dist_cm,
                                    cmap="RdYlGn_r", norm=norm,
                                    s=65, zorder=5,
                                    edgecolors="#555", linewidths=0.5)
            cbar = fig.colorbar(sc, ax=ax_main, pad=0.02, fraction=0.04)
            cbar.set_label("殘差距離 (cm)", color=TEXT, fontsize=8)
            cbar.ax.yaxis.set_tick_params(color=TEXT, labelcolor=TEXT, labelsize=7)

        # 十字基準線
        ax_main.axhline(0, color=TEXT, linewidth=0.8)
        ax_main.axvline(0, color=TEXT, linewidth=0.8)

        lim = max(max(abs(v) for v in dx_cm + dy_cm) * 1.25, 0.5)
        ax_main.set_xlim(-lim, lim)
        ax_main.set_ylim(-lim, lim)
        ax_main.set_aspect("equal")
        ax_main.set_xlabel("ΔX (cm)", color=TEXT, fontsize=10)
        ax_main.set_ylabel("ΔY (cm)", color=TEXT, fontsize=10)
        ax_main.set_title("全域偏移量分佈圖（LOO 殘差，中心於原點）",
                          color=TEXT, fontsize=11, pad=8)
        ax_main.grid(color=GRID, linewidth=0.4)

        # ── 右上：ΔX 直方圖 ─────────────────────────────────────────
        bins = max(6, len(dx_cm))
        ax_hist_x.hist(dx_cm, bins=bins, color="#3a7bd5", alpha=0.85,
                       edgecolor=PANEL, linewidth=0.4)
        ax_hist_x.axvline(0, color=AMBER, linewidth=1.2, linestyle="--")
        ax_hist_x.set_xlabel("ΔX (cm)", color=TEXT, fontsize=8)
        ax_hist_x.set_ylabel("頻率", color=TEXT, fontsize=8)
        ax_hist_x.set_title(f"ΔX 分佈   RMSE_X = {rmse_x_cm:.2f} cm",
                            color=TEXT, fontsize=9)
        ax_hist_x.grid(color=GRID, linewidth=0.3, axis="y")

        # ── 右下：ΔY 直方圖 ─────────────────────────────────────────
        ax_hist_y.hist(dy_cm, bins=bins, color="#2ecc87", alpha=0.85,
                       edgecolor=PANEL, linewidth=0.4)
        ax_hist_y.axvline(0, color=AMBER, linewidth=1.2, linestyle="--")
        ax_hist_y.set_xlabel("ΔY (cm)", color=TEXT, fontsize=8)
        ax_hist_y.set_ylabel("頻率", color=TEXT, fontsize=8)
        ax_hist_y.set_title(f"ΔY 分佈   RMSE_Y = {rmse_y_cm:.2f} cm",
                            color=TEXT, fontsize=9)
        ax_hist_y.grid(color=GRID, linewidth=0.3, axis="y")

        # ── 主標題 ──────────────────────────────────────────────────
        warning_tag = ""
        title_color = TEXT
        if rmse["total"] > self.RMSE_WARNING_THRESHOLD:
            warning_tag = "  ⚠ 超標"
            title_color = RED

        fig.suptitle(
            f"全域 TPS 控制點殘差品管報告（LOO 交叉驗證）\n"
            f"總 RMSE = {rmse_tot_cm:.2f} cm　"
            f"控制點數 = {len(pairs)}{warning_tag}",
            color=title_color, fontsize=12, fontweight="bold", y=0.97
        )

        # ── 儲存 ────────────────────────────────────────────────────
        prefix   = "[WARNING]_" if warning_tag else ""
        filename = f"{prefix}GLOBAL_error_distribution.png"
        filepath = os.path.join(self.output_dir, filename)
        fig.savefig(filepath, dpi=150, bbox_inches="tight", facecolor=BG)
        plt.close(fig)
        print(f"    品管圖已儲存：{filepath}")
