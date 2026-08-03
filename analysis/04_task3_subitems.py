# -*- coding: utf-8 -*-
"""タスク③：MMSE下位項目・CDR6領域の群間比較（探索的解析／BH-FDR補正）"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import *
import matplotlib.pyplot as plt
import numpy as np, pandas as pd
from scipy import stats

mmse, cdr, moca, psy = load_all()
ari, nasi, grp = define_groups(mmse, psy)
IDS = ari + nasi

def bh_fdr(p):
    """Benjamini-Hochberg FDR補正（q値）"""
    p = np.asarray(p, dtype=float)
    n = len(p); order = np.argsort(p)
    q = np.empty(n)
    prev = 1.0
    for rank, i in enumerate(order[::-1]):
        r = n - rank
        prev = min(prev, p[i] * n / r)
        q[i] = prev
    return q

def analyze(sheet_df, items, item_max, tag, ylabel_fmt, ncols=4, invert=False):
    stats_rows, panels = [], {}
    for it in items:
        W = wide_scores(sheet_df, it, IDS)
        panels[it] = W
        d_ari  = (W.loc[ari,  "18か月"] - W.loc[ari,  "0か月"]).astype(float).dropna()
        d_nasi = (W.loc[nasi, "18か月"] - W.loc[nasi, "0か月"]).astype(float).dropna()
        if d_ari.nunique() <= 1 and d_nasi.nunique() <= 1 and d_ari.iloc[0] == d_nasi.iloc[0]:
            p_mw = 1.0
        else:
            try:    p_mw = stats.mannwhitneyu(d_ari, d_nasi, alternative="two-sided").pvalue
            except Exception: p_mw = 1.0
        try:    p_t = stats.ttest_ind(d_ari, d_nasi, equal_var=False).pvalue
        except Exception: p_t = np.nan
        # Cliff's delta（効果量：小標本・順序尺度向け）
        a, b = d_ari.values, d_nasi.values
        cd = (np.sum(a[:, None] > b[None, :]) - np.sum(a[:, None] < b[None, :])) / (len(a) * len(b))
        stats_rows.append(dict(項目=it, 満点=item_max.get(it, ""),
                               あり_Δ18M=f"{d_ari.mean():+.2f} ± {d_ari.std(ddof=1):.2f}",
                               なし_Δ18M=f"{d_nasi.mean():+.2f} ± {d_nasi.std(ddof=1):.2f}",
                               差_あり引くなし=round(d_ari.mean() - d_nasi.mean(), 3),
                               Cliffs_delta=round(cd, 3),
                               p_MannWhitney_補正前=round(p_mw, 4),
                               p_Welch_補正前=round(p_t, 4) if pd.notna(p_t) else np.nan))
    S = pd.DataFrame(stats_rows)
    S["q_MannWhitney_FDR補正後"] = np.round(bh_fdr(S["p_MannWhitney_補正前"].values), 4)
    S["q_Welch_FDR補正後"] = np.round(bh_fdr(S["p_Welch_補正前"].fillna(1).values), 4)
    S = S.sort_values("p_MannWhitney_補正前").reset_index(drop=True)
    S.to_csv(OUT / f"task3_{tag}_群間比較_FDR補正.csv", index=False, encoding="utf-8-sig")

    # ---- パネル図（平均±95%CI） ----
    nrows = int(np.ceil(len(items) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(3.15 * ncols, 2.65 * nrows))
    axes = np.atleast_1d(axes).ravel()
    x = np.array(TP_MONTHS, dtype=float)
    for k, it in enumerate(items):
        ax = axes[k]; W = panels[it]
        for ids, color, off in [(ari, C_ARI, -0.30), (nasi, C_NASI, 0.30)]:
            ms = [mean_ci(W.loc[ids, t]) for t in TP_LABELS]
            m = np.array([a[0] for a in ms]); h = np.array([a[1] for a in ms])
            ax.errorbar(x + off, m, yerr=h, fmt="-o", color=color, lw=1.9, markersize=5,
                        capsize=3, capthick=1.2, elinewidth=1.2,
                        markeredgecolor="white", markeredgewidth=0.8)
        ax.set_xticks(TP_MONTHS); ax.set_xticklabels(["0", "6", "12", "18"], fontsize=10)
        ax.set_xlim(-2, 20)
        ax.tick_params(labelsize=10)
        mx = item_max.get(it)
        ttl = f"{it}（満点 {mx}）" if mx else it
        ax.set_title(ttl, fontsize=11.5, pad=6)
        # 全時点で値が一定の項目（天井効果）は軸が潰れるため見やすい範囲を明示
        lo, hi = ax.get_ylim()
        if hi - lo < 0.2:
            c = (hi + lo) / 2
            ax.set_ylim(c - 0.5, c + 0.5)
        if invert: ax.invert_yaxis()
    for k in range(len(items), len(axes)): axes[k].axis("off")
    fig.supxlabel("レカネマブ投与開始からの経過時点（か月）", fontsize=12, y=0.005)
    fig.supylabel(ylabel_fmt, fontsize=12, x=0.005)
    handles = [plt.Line2D([], [], color=C_ARI, lw=2.2, marker="o", markersize=6),
               plt.Line2D([], [], color=C_NASI, lw=2.2, marker="o", markersize=6)]
    fig.legend(handles, [f"改善訴えあり (n={len(ari)})", f"改善訴えなし (n={len(nasi)})"],
               loc="lower center", ncol=2, fontsize=11.5, bbox_to_anchor=(0.5, -0.035))
    fig.tight_layout(rect=[0.02, 0.045, 1, 1])
    fig.savefig(FIG / f"fig_3_{tag}_群間比較パネル.png")
    plt.close(fig)
    return S, panels

print("=" * 78)
print("タスク③-1  MMSE下位項目（11項目）  ※探索的解析・BH-FDR補正")
print("=" * 78)
S1, P1 = analyze(mmse, MMSE_SUBITEMS, MMSE_SUB_MAX, "MMSE下位項目",
                 "各下位項目の平均得点（点）± 95% CI", ncols=4)
print(S1.to_string(index=False))

print("\n" + "=" * 78)
print("タスク③-2  CDR 6領域  ※探索的解析・BH-FDR補正（高値ほど重度）")
print("=" * 78)
S2, P2 = analyze(cdr, CDR_DOMAINS, {}, "CDR6領域",
                 "各領域スコア（高値ほど重度）± 95% CI", ncols=3)
print(S2.to_string(index=False))

# CDR-SB も参考として
W = wide_scores(cdr, "CDR-SB_自動計算", IDS)
d1 = (W.loc[ari, "18か月"] - W.loc[ari, "0か月"]).astype(float).dropna()
d2 = (W.loc[nasi, "18か月"] - W.loc[nasi, "0か月"]).astype(float).dropna()
print(f"\n[参考] CDR-SB Δ18M: あり {d1.mean():+.2f}±{d1.std(ddof=1):.2f} (n={len(d1)}) / "
      f"なし {d2.mean():+.2f}±{d2.std(ddof=1):.2f} (n={len(d2)}) "
      f"| Mann-Whitney p={stats.mannwhitneyu(d1, d2, alternative='two-sided').pvalue:.3f}")

# 補正後に有意な項目
sig = S1[S1["q_MannWhitney_FDR補正後"] < 0.05]
print(f"\n★ MMSE下位項目：FDR補正後 q<0.05 の項目数 = {len(sig)} / {len(S1)}")
sig2 = S2[S2["q_MannWhitney_FDR補正後"] < 0.05]
print(f"★ CDR6領域：FDR補正後 q<0.05 の項目数 = {len(sig2)} / {len(S2)}")
print(f"★ 補正前 p<0.05 の項目数：MMSE {int((S1['p_MannWhitney_補正前']<0.05).sum())} / CDR {int((S2['p_MannWhitney_補正前']<0.05).sum())}")

# 注目項目の選定：p値ではなく「Δ18M平均の群間差の絶対値」で乖離の大きさを評価する。
# （1点満点の項目はp値が小さく出やすいが、1例の増減で動くため臨床的な乖離とは言えない）
S1["乖離_絶対値"] = S1["差_あり引くなし"].abs()
rank = S1.sort_values("乖離_絶対値", ascending=False).reset_index(drop=True)
print("\n=== Δ18M 群間差の絶対値による順位（乖離の大きさ） ===")
print(rank[["項目", "満点", "差_あり引くなし", "Cliffs_delta",
            "p_MannWhitney_補正前", "q_MannWhitney_FDR補正後"]].to_string())
S1.drop(columns=["乖離_絶対値"]).to_csv(
    OUT / "task3_MMSE下位項目_群間比較_FDR補正.csv", index=False, encoding="utf-8-sig")

top2 = rank.head(2)["項目"].tolist()
print(f"\n★ 群間の乖離が大きい上位2項目（絶対差基準）：{top2}")
r_dr = S1[S1["項目"] == "遅延再生"].iloc[0]
print(f"★ 既存テーマ「遅延再生」：差={r_dr['差_あり引くなし']:+.3f}点 "
      f"(順位 {rank[rank['項目']=='遅延再生'].index[0]+1}/11), "
      f"補正前 p={r_dr['p_MannWhitney_補正前']:.3f} → 上位2項目には入らない")
fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.3))
x = np.array(TP_MONTHS, dtype=float)
for ax, it in zip(axes, top2):
    W = P1[it]
    for ids, color, off, lab in [(ari, C_ARI, -0.30, f"改善訴えあり (n={len(ari)})"),
                                 (nasi, C_NASI, 0.30, f"改善訴えなし (n={len(nasi)})")]:
        ms = [mean_ci(W.loc[ids, t]) for t in TP_LABELS]
        m = np.array([a[0] for a in ms]); h = np.array([a[1] for a in ms])
        ax.errorbar(x + off, m, yerr=h, fmt="-o", color=color, lw=2.6, markersize=8,
                    capsize=5, capthick=1.6, elinewidth=1.6, label=lab,
                    markeredgecolor="white", markeredgewidth=1.2)
    r = S1[S1["項目"] == it].iloc[0]
    ax.set_xticks(TP_MONTHS); ax.set_xticklabels(TP_LABELS)
    ax.set_xlim(-2, 20)
    ax.set_title(f"{it}（満点 {MMSE_SUB_MAX[it]}）\n"
                 f"補正前 p={r['p_MannWhitney_補正前']:.3f} / FDR補正後 q={r['q_MannWhitney_FDR補正後']:.3f}",
                 fontsize=12.5, pad=8)
    ax.set_xlabel("経過時点")
axes[0].set_ylabel("平均得点（点）± 95% CI")
axes[0].legend(loc="best", fontsize=11)
fig.tight_layout()
fig.savefig(FIG / "fig_3_注目下位項目_拡大.png")
plt.close(fig)
print("図を出力しました。")

# ============================== 分散の比較（結果3のばらつき主張の検定） ==============================
print("\n" + "=" * 78)
print("結果3　個人内変動幅・Δ18MのSDの群間差についての検定（分散の比較）")
print("=" * 78)
W_mmse = wide_scores(mmse, "合計_原資料記載値", IDS)
D18 = (W_mmse["18か月"] - W_mmse["0か月"]).astype(float)
d_ari = D18.loc[ari].dropna(); d_nasi = D18.loc[nasi].dropna()
lev = stats.levene(d_ari, d_nasi, center="median")
print(f"Δ18MのSD：訴えあり {d_ari.std(ddof=1):.2f} (n={len(d_ari)}) / 訴えなし {d_nasi.std(ddof=1):.2f} (n={len(d_nasi)})")
print(f"Levene検定（分散の均一性）：F={lev.statistic:.3f}, p={lev.pvalue:.3f}")

rng_ = W_mmse.loc[IDS, TP_LABELS].astype(float).max(axis=1) - W_mmse.loc[IDS, TP_LABELS].astype(float).min(axis=1)
r_ari = rng_.loc[ari]; r_nasi = rng_.loc[nasi]
lev2 = stats.levene(r_ari, r_nasi, center="median")
mw_rng = stats.mannwhitneyu(r_ari, r_nasi, alternative="two-sided")
print(f"個人内変動幅：訴えあり {r_ari.mean():.2f} (n={len(r_ari)}) / 訴えなし {r_nasi.mean():.2f} (n={len(r_nasi)})")
print(f"Levene検定（変動幅の分散均一性）：F={lev2.statistic:.3f}, p={lev2.pvalue:.3f}")
print(f"Mann-Whitney（変動幅の中心の比較）：p={mw_rng.pvalue:.3f}")
