# -*- coding: utf-8 -*-
"""タスク②-1：改善訴えあり/なし群の個別症例MMSE推移
 (a) 重ね合わせ図（メイン候補）  (b) 群別2パネル図
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import *
import matplotlib.pyplot as plt
import numpy as np, pandas as pd

mmse, cdr, moca, psy = load_all()
ari, nasi, grp = define_groups(mmse, psy)
W = wide_scores(mmse, "合計_原資料記載値", ari + nasi)

# --- 結果5との整合性チェック（平均値が既存スライドと一致するか） ---
print("=== 結果5スライドとの整合性チェック（平均MMSE） ===")
for label, ids, expect in [("改善訴えあり", ari, [22.89, 24.56, 23.11, 23.11]),
                           ("改善訴えなし", nasi, [24.25, 24.15, 23.84, 23.50])]:
    got = [round(mean_ci(W.loc[ids, t])[0], 2) for t in TP_LABELS]
    ns  = [mean_ci(W.loc[ids, t])[2] for t in TP_LABELS]
    print(f"{label}: 計算値={got} n={ns} / スライド値={expect} → {'一致' if got==expect else '★不一致★'}")

x = np.array(TP_MONTHS, dtype=float)

def draw_traj(ax, ids, color, lw=1.3, alpha=0.55, ms=4):
    for pid in ids:
        y = W.loc[pid, TP_LABELS].astype(float).values
        ok = ~np.isnan(y)
        ax.plot(x[ok], y[ok], "-o", color=color, lw=lw, alpha=alpha,
                markersize=ms, markeredgewidth=0, zorder=2)

def draw_mean(ax, ids, color, label):
    ms = [mean_ci(W.loc[ids, t]) for t in TP_LABELS]
    m = np.array([a[0] for a in ms])
    ax.plot(x, m, "-", color=color, lw=3.2, zorder=5, label=label,
            solid_capstyle="round")
    ax.plot(x, m, "o", color=color, markersize=8, markeredgecolor="white",
            markeredgewidth=1.4, zorder=6)

def style(ax, ylab="MMSE実測値（点）"):
    ax.set_xticks(TP_MONTHS); ax.set_xticklabels(TP_LABELS)
    ax.set_xlim(-1.2, 19.2)
    ax.set_ylim(14.5, 30.5); ax.set_yticks(range(16, 31, 2))
    ax.set_xlabel("レカネマブ投与開始からの経過時点")
    ax.set_ylabel(ylab)

# ============ (a) 重ね合わせ図（メイン候補） ============
fig, ax = plt.subplots(figsize=(11.6, 5.2))
draw_traj(ax, nasi, C_NASI)          # 20例（下層）
draw_traj(ax, ari,  C_ARI)           # 9例（上層）
draw_mean(ax, nasi, C_NASI, "改善訴えなし 群平均 (n=20)")
draw_mean(ax, ari,  C_ARI,  "改善訴えあり 群平均 (n=9)")
style(ax)
h = [plt.Line2D([], [], color=C_ARI, lw=1.6, marker="o", markersize=4, alpha=0.7),
     plt.Line2D([], [], color=C_NASI, lw=1.6, marker="o", markersize=4, alpha=0.7),
     plt.Line2D([], [], color=C_ARI, lw=3.2, marker="o", markersize=8,
                markeredgecolor="white", markeredgewidth=1.2),
     plt.Line2D([], [], color=C_NASI, lw=3.2, marker="o", markersize=8,
                markeredgecolor="white", markeredgewidth=1.2)]
ax.legend(h, ["赤：改善訴えあり 個別症例 (n=9)", "青：改善訴えなし 個別症例 (n=20)",
              "改善訴えあり 群平均", "改善訴えなし 群平均"],
          loc="lower center", bbox_to_anchor=(0.5, -0.30), ncol=2, fontsize=11)
fig.savefig(FIG / "fig_2_1a_個別症例MMSE推移_重ね合わせ.png")
plt.close(fig)

# ============ (b) 群別2パネル図 ============
fig, axes = plt.subplots(1, 2, figsize=(12.0, 5.0), sharey=True)
for ax, ids, color, title in [
        (axes[0], ari,  C_ARI,  f"改善訴えあり（n={len(ari)}）"),
        (axes[1], nasi, C_NASI, f"改善訴えなし（n={len(nasi)}）")]:
    a = 0.75 if ids is ari else 0.45
    lw = 1.6 if ids is ari else 1.2
    draw_traj(ax, ids, color, lw=lw, alpha=a, ms=4)
    draw_mean(ax, ids, color, "群平均")
    style(ax, ylab="MMSE実測値（点）" if ids is ari else "")
    ax.set_title(title, fontsize=14, pad=10)
    ax.legend([plt.Line2D([], [], color=color, lw=3.2, marker="o", markersize=8,
                          markeredgecolor="white", markeredgewidth=1.2)],
              ["群平均"], loc="lower left", fontsize=11)
fig.subplots_adjust(wspace=0.08)
fig.savefig(FIG / "fig_2_1b_個別症例MMSE推移_群別2パネル.png")
plt.close(fig)

# ============ 記述統計（②-2のメモ用） ============
rows = []
for label, ids in [("訴えあり", ari), ("訴えなし", nasi)]:
    d = (W.loc[ids, "18か月"] - W.loc[ids, "0か月"]).astype(float)
    peak = W.loc[ids, TP_LABELS].astype(float).max(axis=1) - W.loc[ids, "0か月"].astype(float)
    rng  = W.loc[ids, TP_LABELS].astype(float).max(axis=1) - W.loc[ids, TP_LABELS].astype(float).min(axis=1)
    rows.append(dict(群=label, n=len(ids),
                     ベースラインMMSE平均=round(W.loc[ids, "0か月"].mean(), 2),
                     ベースラインSD=round(W.loc[ids, "0か月"].std(ddof=1), 2),
                     Δ18M平均=round(d.mean(), 2), Δ18M_SD=round(d.std(ddof=1), 2),
                     Δ18M最小=int(d.min()), Δ18M最大=int(d.max()),
                     改善例数=int((d > 0).sum()), 不変例数=int((d == 0).sum()),
                     悪化例数=int((d < 0).sum()),
                     個人内変動幅の平均=round(rng.mean(), 2),
                     ピーク上昇幅の平均=round(peak.mean(), 2)))
desc = pd.DataFrame(rows)
desc.to_csv(OUT / "task2_1_記述統計.csv", index=False, encoding="utf-8-sig")
print("\n=== 個別推移の記述統計 ===")
print(desc.to_string(index=False))

# 個票（付録用）
tbl = W.copy()
tbl.insert(0, "群", [grp[i] for i in tbl.index])
tbl["Δ18M"] = tbl["18か月"] - tbl["0か月"]
tbl.to_csv(OUT / "task2_1_個別症例MMSE_29例.csv", encoding="utf-8-sig")
print("\n図を出力:", FIG / "fig_2_1a_個別症例MMSE推移_重ね合わせ.png",
      "/", FIG / "fig_2_1b_個別症例MMSE推移_群別2パネル.png")
