# -*- coding: utf-8 -*-
"""応用Ver：文献調査_結果1to結果5.md「応用Ver 図の設計仕様」の実装
参照：Cano S, et al. J Prev Alzheimers Dis 2022 (doi:10.14283/jpad.2022.102)
  アンカー = 症状改善の訴え（主観的・臨床的判断）
  ターゲット測度 = ベースラインからのΔMMSE
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import *
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np, pandas as pd
from scipy import stats

rng = np.random.default_rng(20250805)

mmse, cdr, moca, psy = load_all()
ari, nasi, grp = define_groups(mmse, psy)
W = wide_scores(mmse, "合計_原資料記載値", ari + nasi)
D = W.sub(W["0か月"], axis=0)          # ΔMMSE（ベースラインから）
DTP = ["6か月", "12か月", "18か月"]
DX = [6, 12, 18]

# 参照帯：Aakre JA, et al. Alzheimers Dement (N Y) 2025 (doi:10.1002/trc2.70160)
# MCI発症をアンカーとしたMMSE年間変化 -1.01 (95%CI -1.12 to -0.91)
ANN = -1.01

# ---------- パネルA：ΔMMSE 平均±95%CI＋個別点 ----------
fig, ax = plt.subplots(figsize=(11.6, 5.0))
# 参照帯（年 -1.01 点の直線的外挿）
xb = np.array([0, 6, 12, 18], dtype=float)
ax.fill_between(xb, ANN * xb / 12 - 0.35, ANN * xb / 12 + 0.35,
                color="#BFBFBF", alpha=0.30, zorder=0, linewidth=0)
ax.axhline(0, color="#595959", lw=1.0, zorder=1)

for ids, color, label, off in [(ari, C_ARI, f"改善訴えあり (n={len(ari)})", -0.55),
                               (nasi, C_NASI, f"改善訴えなし (n={len(nasi)})", 0.55)]:
    ms = [mean_ci(D.loc[ids, t]) for t in DTP]
    m = np.array([a[0] for a in ms]); h = np.array([a[1] for a in ms])
    xs = np.array(DX, dtype=float) + off
    # 個別点（ジッター）
    for j, t in enumerate(DTP):
        y = D.loc[ids, t].astype(float).values
        y = y[~np.isnan(y)]
        ax.scatter(xs[j] + rng.uniform(-0.42, 0.42, len(y)), y, s=22, color=color,
                   alpha=0.35, linewidths=0, zorder=2)
    ax.errorbar(xs, m, yerr=h, fmt="-o", color=color, lw=2.6, markersize=9,
                markeredgecolor="white", markeredgewidth=1.4,
                capsize=6, capthick=1.8, elinewidth=1.8, zorder=5, label=label)

ax.set_xticks(DX); ax.set_xticklabels(DTP)
ax.set_xlim(3.5, 20.5)
ax.set_ylim(-10.5, 7.5); ax.set_yticks(range(-10, 8, 2))
ax.set_xlabel("レカネマブ投与開始からの経過時点")
ax.set_ylabel("Δ MMSE（ベースラインからの変化量、点）")
hs, ls = ax.get_legend_handles_labels()
hs.append(plt.Rectangle((0, 0), 1, 1, color="#BFBFBF", alpha=0.30))
ls.append("参照帯：年 −1.01 点の低下（Aakre 2025、判定基準ではない）")
ax.legend(hs, ls, loc="lower center", bbox_to_anchor=(0.5, -0.30), ncol=3, fontsize=10.5)
fig.savefig(FIG / "fig_ouyouA_ΔMMSE推移_平均95CI_個別点.png")
plt.close(fig)

# ---------- パネルB：18か月ΔMMSE ドットプロット（ベースラインMMSEで着色） ----------
fig, ax = plt.subplots(figsize=(7.2, 5.0))
cmap = plt.get_cmap("viridis")
base_all = W["0か月"].astype(float)
vmin, vmax = base_all.min(), base_all.max()
norm = plt.Normalize(vmin, vmax)

for k, (ids, color, label) in enumerate([(ari, C_ARI, f"改善訴えあり\n(n={len(ari)})"),
                                         (nasi, C_NASI, f"改善訴えなし\n(n={len(nasi)})")]):
    y = D.loc[ids, "18か月"].astype(float).values
    bp = ax.boxplot([y], positions=[k], widths=0.5, showfliers=False,
                    medianprops=dict(color=color, lw=2.2),
                    boxprops=dict(color="#888888", lw=1.2),
                    whiskerprops=dict(color="#888888", lw=1.2),
                    capprops=dict(color="#888888", lw=1.2))
    xj = k + rng.uniform(-0.16, 0.16, len(y))
    ax.scatter(xj, y, s=70, c=base_all.loc[ids].values, cmap=cmap, norm=norm,
               edgecolors=color, linewidths=1.6, zorder=4)

ax.axhline(0, color="#595959", lw=1.0)
ax.axhspan(ANN * 1.5 - 0.35, ANN * 1.5 + 0.35, color="#BFBFBF", alpha=0.30, zorder=0)
ax.set_xticks([0, 1]); ax.set_xticklabels([f"改善訴えあり\n(n={len(ari)})", f"改善訴えなし\n(n={len(nasi)})"])
ax.set_xlim(-0.6, 1.6)
ax.set_ylim(-10.5, 6.5); ax.set_yticks(range(-10, 7, 2))
ax.set_ylabel("18か月時点の Δ MMSE（点）")
sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm); sm.set_array([])
cb = fig.colorbar(sm, ax=ax, pad=0.03)
cb.set_label("ベースラインMMSE（点）", fontsize=11)
cb.outline.set_edgecolor("#888888")
fig.savefig(FIG / "fig_ouyouB_18か月ΔMMSE_ドットプロット.png")
plt.close(fig)

# ---------- 付随表：参照帯を超えて低下した症例の割合 ----------
thr = ANN * 1.5   # 18か月 = 1.5年 → -1.515点
rows = []
for label, ids in [("改善訴えあり", ari), ("改善訴えなし", nasi)]:
    d = D.loc[ids, "18か月"].astype(float)
    n = d.notna().sum(); k = int((d < thr).sum())
    rows.append(dict(群=label, n=int(n), 参照帯を超えて低下した症例数=k,
                     割合=f"{k/n*100:.1f}%",
                     Δ18M平均=round(d.mean(), 2), Δ18M_SD=round(d.std(ddof=1), 2),
                     Δ18M中央値=round(d.median(), 2)))
ref = pd.DataFrame(rows)
ref.to_csv(OUT / "ouyou_参照帯を超えた低下の割合.csv", index=False, encoding="utf-8-sig")
print("=== 参照帯（18か月で −1.52 点＝年−1.01点相当）を超えて低下した症例 ===")
print(ref.to_string(index=False))

# 割合の群間比較（Fisher）
a = int((D.loc[ari, "18か月"] < thr).sum()); b = len(ari) - a
c = int((D.loc[nasi, "18か月"] < thr).sum()); d_ = len(nasi) - c
print("Fisher正確検定 p =", round(stats.fisher_exact([[a, b], [c, d_]])[1], 3))

# ΔMMSE 群間比較（結果5の再現確認を兼ねる）
print("\n=== Δ MMSE 群間比較 ===")
for t in DTP:
    x1 = D.loc[ari, t].dropna().astype(float); x2 = D.loc[nasi, t].dropna().astype(float)
    tt = stats.ttest_ind(x1, x2, equal_var=False)
    mw = stats.mannwhitneyu(x1, x2, alternative="two-sided")
    print(f"{t}: あり {x1.mean():+.2f}±{x1.std(ddof=1):.2f} (n={len(x1)}) / "
          f"なし {x2.mean():+.2f}±{x2.std(ddof=1):.2f} (n={len(x2)}) "
          f"| Welch p={tt.pvalue:.3f} / Mann-Whitney p={mw.pvalue:.3f}")

# 18か月MMSE実測値の群間比較（結果5スライドの p 値を再現）
x1 = W.loc[ari, "18か月"].astype(float); x2 = W.loc[nasi, "18か月"].astype(float)
print("\n=== 結果5スライドのp値再現（18か月MMSE実測値） ===")
print(f"Welch t p={stats.ttest_ind(x1, x2, equal_var=False).pvalue:.3f} (スライド 0.804)")
print(f"Mann-Whitney p={stats.mannwhitneyu(x1, x2, alternative='two-sided').pvalue:.3f} (スライド 0.617)")
# ベースライン調整（ANCOVA相当：OLS）
import itertools
y  = np.r_[x1.values, x2.values]
g  = np.r_[np.ones(len(x1)), np.zeros(len(x2))]
b0 = np.r_[W.loc[ari, "0か月"].values, W.loc[nasi, "0か月"].values].astype(float)
X  = np.column_stack([np.ones(len(y)), g, b0])
beta, *_ = np.linalg.lstsq(X, y, rcond=None)
resid = y - X @ beta
dof = len(y) - X.shape[1]
s2 = resid @ resid / dof
cov = s2 * np.linalg.inv(X.T @ X)
tval = beta[1] / np.sqrt(cov[1, 1])
p_adj = 2 * stats.t.sf(abs(tval), dof)
print(f"ベースラインMMSE調整後 p={p_adj:.3f} (スライド 0.879)")
