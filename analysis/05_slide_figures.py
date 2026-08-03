# -*- coding: utf-8 -*-
"""スライド貼り込み用の図（コンテンツ枠 12.30 x 4.55 inch に合わせた版）を生成する。
解析用の図（02〜04）はそのまま記録用に残し、ここではレイアウトのみ調整する。"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import *
import matplotlib.pyplot as plt
import numpy as np, pandas as pd
from scipy import stats

SLIDE = OUT / "slide_figures"; SLIDE.mkdir(exist_ok=True)
W_IN, H_IN = 12.30, 4.55
rng = np.random.default_rng(20250805)

mmse, cdr, moca, psy = load_all()
ari, nasi, grp = define_groups(mmse, psy)
IDS = ari + nasi
W = wide_scores(mmse, "合計_原資料記載値", IDS)
D = W.sub(W["0か月"], axis=0)
x = np.array(TP_MONTHS, dtype=float)

# ================= スライド用①：ΔMMSE（応用Ver パネルA） =================
ANN = -1.01
fig, ax = plt.subplots(figsize=(W_IN, H_IN))
xb = np.array([0, 6, 12, 18], dtype=float)
ax.fill_between(xb, ANN * xb / 12 - 0.35, ANN * xb / 12 + 0.35,
                color="#BFBFBF", alpha=0.30, zorder=0, linewidth=0)
ax.axhline(0, color="#595959", lw=1.0, zorder=1)
DTP, DX = ["6か月", "12か月", "18か月"], [6, 12, 18]
for ids, color, label, off in [(ari, C_ARI, f"改善訴えあり (n={len(ari)})", -0.55),
                               (nasi, C_NASI, f"改善訴えなし (n={len(nasi)})", 0.55)]:
    ms = [mean_ci(D.loc[ids, t]) for t in DTP]
    m = np.array([a[0] for a in ms]); h = np.array([a[1] for a in ms])
    xs = np.array(DX, dtype=float) + off
    for j, t in enumerate(DTP):
        y = D.loc[ids, t].astype(float).dropna().values
        ax.scatter(xs[j] + rng.uniform(-0.42, 0.42, len(y)), y, s=20, color=color,
                   alpha=0.35, linewidths=0, zorder=2)
    ax.errorbar(xs, m, yerr=h, fmt="-o", color=color, lw=2.6, markersize=9,
                markeredgecolor="white", markeredgewidth=1.4,
                capsize=6, capthick=1.8, elinewidth=1.8, zorder=5, label=label)
ax.set_xticks(DX); ax.set_xticklabels(DTP)
ax.set_xlim(3.5, 20.5); ax.set_ylim(-10.5, 8.5); ax.set_yticks(range(-10, 9, 2))
ax.set_xlabel("レカネマブ投与開始からの経過時点")
ax.set_ylabel("Δ MMSE（ベースラインからの変化量、点）")
hs, ls = ax.get_legend_handles_labels()
hs.append(plt.Rectangle((0, 0), 1, 1, color="#BFBFBF", alpha=0.35))
ls.append("参照帯：年 −1.01 点の低下（Aakre 2025）")
ax.legend(hs, ls, loc="upper right", fontsize=10.5, ncol=1)
fig.tight_layout()
fig.savefig(SLIDE / "slide_ΔMMSE_アンカー別推移.png"); plt.close(fig)

# ================= スライド用②：個別症例MMSE推移（重ね合わせ） =================
fig, ax = plt.subplots(figsize=(W_IN, H_IN))
for ids, color, lw, al in [(nasi, C_NASI, 1.2, 0.50), (ari, C_ARI, 1.4, 0.60)]:
    for pid in ids:
        y = W.loc[pid, TP_LABELS].astype(float).values
        ok = ~np.isnan(y)
        ax.plot(x[ok], y[ok], "-o", color=color, lw=lw, alpha=al,
                markersize=3.5, markeredgewidth=0, zorder=2)
for ids, color in [(nasi, C_NASI), (ari, C_ARI)]:
    m = np.array([mean_ci(W.loc[ids, t])[0] for t in TP_LABELS])
    ax.plot(x, m, "-", color=color, lw=3.4, zorder=5, solid_capstyle="round")
    ax.plot(x, m, "o", color=color, markersize=8.5, markeredgecolor="white",
            markeredgewidth=1.5, zorder=6)
ax.set_xticks(TP_MONTHS); ax.set_xticklabels(TP_LABELS)
ax.set_xlim(-1.2, 19.4); ax.set_ylim(14.5, 30.5); ax.set_yticks(range(16, 31, 2))
ax.set_xlabel("レカネマブ投与開始からの経過時点")
ax.set_ylabel("MMSE実測値（点）")
h = [plt.Line2D([], [], color=C_ARI, lw=1.6, marker="o", markersize=4, alpha=0.75),
     plt.Line2D([], [], color=C_NASI, lw=1.6, marker="o", markersize=4, alpha=0.65),
     plt.Line2D([], [], color=C_ARI, lw=3.4, marker="o", markersize=8.5,
                markeredgecolor="white", markeredgewidth=1.3),
     plt.Line2D([], [], color=C_NASI, lw=3.4, marker="o", markersize=8.5,
                markeredgecolor="white", markeredgewidth=1.3)]
ax.legend(h, ["赤：改善訴えあり 個別症例 (n=9)", "青：改善訴えなし 個別症例 (n=20)",
              "改善訴えあり 群平均", "改善訴えなし 群平均"],
          loc="lower left", ncol=2, fontsize=10.5)
fig.tight_layout()
fig.savefig(SLIDE / "slide_個別症例MMSE推移_重ね合わせ.png"); plt.close(fig)

# ================= スライド用③：MMSE下位項目パネル（6列×2段） =================
ncols, nrows = 6, 2
fig, axes = plt.subplots(nrows, ncols, figsize=(W_IN, H_IN))
axes = axes.ravel()
for k, it in enumerate(MMSE_SUBITEMS):
    ax = axes[k]; Wi = wide_scores(mmse, it, IDS)
    for ids, color, off in [(ari, C_ARI, -0.30), (nasi, C_NASI, 0.30)]:
        ms = [mean_ci(Wi.loc[ids, t]) for t in TP_LABELS]
        m = np.array([a[0] for a in ms]); h = np.array([a[1] for a in ms])
        ax.errorbar(x + off, m, yerr=h, fmt="-o", color=color, lw=1.5, markersize=3.4,
                    capsize=2.2, capthick=1.0, elinewidth=1.0,
                    markeredgecolor="white", markeredgewidth=0.6)
    ax.set_xticks(TP_MONTHS); ax.set_xticklabels(["0", "6", "12", "18"], fontsize=8)
    ax.set_xlim(-2.5, 20.5); ax.tick_params(labelsize=8)
    ax.set_title(f"{it}（{MMSE_SUB_MAX[it]}点満点）", fontsize=9.5, pad=3)
    lo, hi = ax.get_ylim()
    if hi - lo < 0.2:
        c = (hi + lo) / 2; ax.set_ylim(c - 0.5, c + 0.5)
# 12枚目のセルを凡例に使う
lg = axes[11]; lg.axis("off")
lg.legend([plt.Line2D([], [], color=C_ARI, lw=2.0, marker="o", markersize=5),
           plt.Line2D([], [], color=C_NASI, lw=2.0, marker="o", markersize=5)],
          [f"改善訴えあり\n(n={len(ari)})", f"改善訴えなし\n(n={len(nasi)})"],
          loc="center", fontsize=10, handlelength=1.8)
fig.supxlabel("経過時点（か月）", fontsize=10, y=0.012)
fig.supylabel("平均得点（点）± 95% CI", fontsize=10, x=0.006)
fig.tight_layout(rect=[0.018, 0.028, 1, 1])
fig.savefig(SLIDE / "slide_MMSE下位項目パネル.png"); plt.close(fig)

# ================= 参考スライド用：群別2パネル =================
fig, axes = plt.subplots(1, 2, figsize=(W_IN, H_IN), sharey=True)
for ax, ids, color, title, al, lw in [
        (axes[0], ari,  C_ARI,  f"改善訴えあり（n={len(ari)}）", 0.75, 1.6),
        (axes[1], nasi, C_NASI, f"改善訴えなし（n={len(nasi)}）", 0.45, 1.2)]:
    for pid in ids:
        y = W.loc[pid, TP_LABELS].astype(float).values; ok = ~np.isnan(y)
        ax.plot(x[ok], y[ok], "-o", color=color, lw=lw, alpha=al, markersize=4,
                markeredgewidth=0, zorder=2)
    m = np.array([mean_ci(W.loc[ids, t])[0] for t in TP_LABELS])
    ax.plot(x, m, "-", color=color, lw=3.4, zorder=5)
    ax.plot(x, m, "o", color=color, markersize=8.5, markeredgecolor="white",
            markeredgewidth=1.5, zorder=6, label="群平均")
    ax.set_xticks(TP_MONTHS); ax.set_xticklabels(TP_LABELS)
    ax.set_xlim(-1.2, 19.2); ax.set_ylim(14.5, 30.5); ax.set_yticks(range(16, 31, 2))
    ax.set_title(title, fontsize=13, pad=6)
    ax.set_xlabel("経過時点")
    ax.legend(loc="lower left", fontsize=10)
axes[0].set_ylabel("MMSE実測値（点）")
fig.tight_layout()
fig.savefig(SLIDE / "slide_個別症例MMSE推移_群別2パネル.png"); plt.close(fig)

# ================= 参考スライド用：18か月ΔMMSE ドットプロット =================
fig, axes = plt.subplots(1, 2, figsize=(W_IN, H_IN), gridspec_kw=dict(width_ratios=[1, 1.25]))
ax = axes[0]
cmap = plt.get_cmap("viridis"); base = W["0か月"].astype(float)
norm = plt.Normalize(base.min(), base.max())
for k, (ids, color) in enumerate([(ari, C_ARI), (nasi, C_NASI)]):
    y = D.loc[ids, "18か月"].astype(float).values
    ax.boxplot([y], positions=[k], widths=0.5, showfliers=False,
               medianprops=dict(color=color, lw=2.2), boxprops=dict(color="#888888", lw=1.2),
               whiskerprops=dict(color="#888888", lw=1.2), capprops=dict(color="#888888", lw=1.2))
    ax.scatter(k + rng.uniform(-0.16, 0.16, len(y)), y, s=60, c=base.loc[ids].values,
               cmap=cmap, norm=norm, edgecolors=color, linewidths=1.5, zorder=4)
ax.axhline(0, color="#595959", lw=1.0)
ax.axhspan(ANN * 1.5 - 0.35, ANN * 1.5 + 0.35, color="#BFBFBF", alpha=0.30, zorder=0)
ax.set_xticks([0, 1]); ax.set_xticklabels([f"改善訴えあり\n(n={len(ari)})", f"改善訴えなし\n(n={len(nasi)})"], fontsize=11)
ax.set_xlim(-0.6, 1.6); ax.set_ylim(-10.5, 6.5); ax.set_yticks(range(-10, 7, 2))
ax.set_ylabel("18か月時点の Δ MMSE（点）")
sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm); sm.set_array([])
cb = fig.colorbar(sm, ax=ax, pad=0.03); cb.set_label("ベースラインMMSE（点）", fontsize=10)
cb.outline.set_edgecolor("#888888"); cb.ax.tick_params(labelsize=9)

# 右：ベースラインMMSE と Δ18M の散布図（重症度のほうが説明するかを確認）
ax2 = axes[1]
for ids, color, lab in [(ari, C_ARI, f"改善訴えあり (n={len(ari)})"),
                        (nasi, C_NASI, f"改善訴えなし (n={len(nasi)})")]:
    ax2.scatter(base.loc[ids], D.loc[ids, "18か月"].astype(float), s=62, color=color,
                alpha=0.75, edgecolors="white", linewidths=1.0, label=lab, zorder=3)
b = base.loc[IDS].values; dd = D.loc[IDS, "18か月"].astype(float).values
sl, ic = np.polyfit(b, dd, 1)
xx = np.linspace(b.min() - 0.5, b.max() + 0.5, 50)
ax2.plot(xx, sl * xx + ic, "--", color="#595959", lw=1.6, zorder=2,
         label=f"全29例の回帰直線（傾き {sl:+.2f}）")
r, p = stats.pearsonr(b, dd)
ax2.axhline(0, color="#595959", lw=1.0, zorder=1)
ax2.set_xlabel("ベースラインMMSE（点）")
ax2.set_ylabel("18か月時点の Δ MMSE（点）")
ax2.set_title(f"ベースライン重症度との関係　r = {r:.2f}, p = {p:.3f}", fontsize=11.5, pad=6)
ax2.legend(loc="lower left", fontsize=9.5)
fig.tight_layout()
fig.savefig(SLIDE / "slide_18か月ΔMMSE_ドットプロット.png"); plt.close(fig)

print(f"ベースラインMMSE と Δ18M の相関： r={r:.3f}, p={p:.4f}, 傾き={sl:+.3f}")
for f in sorted(SLIDE.iterdir()): print("  ", f.name)
