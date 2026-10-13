"""Static PNG versions of the Results charts, for the README and for anyone without the app.

Reads the same frontend/src/data/results.json as the Results view, so the two cannot
disagree. Light surface, the project's validated categorical colours (blue for the thing
the chart is about, orange for the contrast, grey for context), thin marks, hairline grid.

    python export_results.py && python render_figures.py     # -> docs/figures/*.png
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).parent
R = json.loads((HERE.parent / "frontend" / "src" / "data" / "results.json").read_text(encoding="utf-8"))
OUT = HERE.parent / "docs" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
BLUE, ORANGE, AQUA, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#b9b7ae"
BANDS = ["#cde2fb", "#86b6ef", "#2a78d6", "#184f95"]          # ordinal blue: darker = bigger saving

plt.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
    "text.color": INK, "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
})


def finish(fig, ax, title: str, sub: str, name: str) -> None:
    fig.text(0.012, 0.965, title, fontsize=15, fontweight="bold", ha="left", va="top")
    fig.text(0.012, 0.915, sub, fontsize=10, color=INK2, ha="left", va="top")
    fig.savefig(OUT / name, dpi=150, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    print("wrote", OUT / name)


def fig_savings() -> None:
    sv = R["savings"]
    fig, ax = plt.subplots(figsize=(10, 4.4))
    fig.subplots_adjust(top=0.78, left=0.2)
    labels = [s["label"] for s in sv][::-1]
    left = [0.0] * len(sv)
    for i, (key, name) in enumerate([("lt1", "Under 1%"), ("b1_5", "1-5%"), ("b5_20", "5-20%"), ("gt20", "Over 20%")]):
        vals = [s["bands"][key] for s in sv][::-1]
        ax.barh(labels, vals, left=left, color=BANDS[i], edgecolor=SURFACE, linewidth=2, height=0.62, label=name)
        for j, v in enumerate(vals):
            if v >= 9:
                ax.text(left[j] + v / 2, j, f"{v:.0f}%", ha="center", va="center", fontsize=9,
                        color=INK if i < 2 else "white")
        left = [a + b for a, b in zip(left, vals)]
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.grid(axis="y", visible=False)
    ax.legend(ncol=4, frameon=False, loc="lower center", bbox_to_anchor=(0.5, -0.22), fontsize=9)
    finish(fig, ax, "How often does carbon-aware charging pay?",
           "Share of nights in each saving band. Darker = a bigger saving. Same vehicles and window on every grid.", "savings_bands.png")


def fig_hosting() -> None:
    H = R["hosting"]
    gains = [d["gain"] for d in H["draws"]]
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1.15, 1]})
    fig.subplots_adjust(top=0.74, wspace=0.28)
    edges = [3.0 + 0.5 * i for i in range(6)]
    counts = [sum(1 for g in gains if lo <= g < lo + 0.5) for lo in edges]
    cols = [ORANGE if lo <= H["published_first_draw"] < lo + 0.5 else BLUE for lo in edges]
    a.bar([f"{lo:.1f}-{lo + .5:.1f}" for lo in edges], counts, color=cols, width=0.7)
    a.set_title("250 kW transformer, 20 fleet draws", fontsize=10, color=INK2, loc="left")
    a.set_xlabel("hosting-capacity gain (×)")
    a.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    a.grid(axis="x", visible=False)
    a.text(0.98, 0.95, f"median {H['median']:.1f}×\nfirst published {H['published_first_draw']:.1f}× (orange)",
           transform=a.transAxes, ha="right", va="top", fontsize=9, color=INK2)
    rs = H["ratings"]
    for i, r in enumerate(rs):
        b.plot([i, i], [r["gain_min"], r["gain_max"]], color=GREY, linewidth=7, solid_capstyle="round")
        b.plot(i, r["gain"], "o", color=BLUE, markersize=9, markeredgecolor=SURFACE, markeredgewidth=2)
        b.text(i, r["gain_max"] + 0.25, f"{r['gain']:.1f}×", ha="center", fontsize=9, color=INK2)
    b.set_xticks(range(len(rs)), [f"{r['rating_kw']} kW" for r in rs])
    b.set_ylim(0, 8)
    b.set_title("Range across draws, median marked", fontsize=10, color=INK2, loc="left")
    b.grid(axis="x", visible=False)
    finish(fig, a, "How much grid does coordination buy?",
           "The gain is not one number: it depends on the fleet drawn and on how tight the transformer is.", "hosting_capacity.png")


def fig_sensitivity() -> None:
    S = R["sensitivity"]
    rows = S["rows"]
    fig, ax = plt.subplots(figsize=(10, 0.27 * len(rows) + 1.8))
    fig.subplots_adjust(top=1 - 1.1 / (0.27 * len(rows) + 1.8), left=0.34)
    y = range(len(rows))
    ax.axvspan(S["band"][0], S["band"][1], color=BLUE, alpha=0.1, linewidth=0)
    ax.axvline(S["median"], color=INK2, linewidth=1)
    ax.barh(list(y), [r["gain"] for r in rows], color=[BLUE if r["outside_band"] else GREY for r in rows], height=0.62)
    for i, r in enumerate(rows):
        ax.text(r["gain"] + 0.08, i, f"{r['gain']:.1f}×", va="center", fontsize=8, color=INK2)
    ax.set_yticks(list(y), [r["what"] for r in rows], fontsize=8.5)
    ax.set_xlim(0, 11)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}×")
    ax.grid(axis="y", visible=False)
    finish(fig, ax, "Which assumptions move the hosting gain?",
           "Each assumed input changed on its own. Shaded = the spread from redrawing the same fleet. Blue = beyond it.", "sensitivity.png")


def fig_forecast() -> None:
    F = R["forecast"]
    groups = ["Spain 2018 grid", "Spain 2025 grid"]
    series = [("Lags and calendar only", GREY, [F["es2018"]["lags_only"], F["es2025"]["lags_only"]]),
              ("+ day-ahead solar, wind, load", BLUE, [F["es2018"]["with_day_ahead"], F["es2025"]["with_day_ahead"]]),
              ("Deployed model", AQUA, [None, F["es2025"]["deployed"]])]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    fig.subplots_adjust(top=0.78)
    w = 0.24
    for k, (name, col, vals) in enumerate(series):
        xs = [i + (k - 1) * (w + 0.02) for i in range(2)]
        pts = [(x, v) for x, v in zip(xs, vals) if v is not None]
        ax.bar([p[0] for p in pts], [p[1] for p in pts], width=w, color=col, label=name)
        for x, v in pts:
            ax.text(x, v + 1.5, f"{v:.0f}%", ha="center", fontsize=9, color=INK2)
    ax.set_xticks(range(2), groups)
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.grid(axis="x", visible=False)
    ax.legend(frameon=False, ncol=3, loc="lower center", bbox_to_anchor=(0.5, -0.22), fontsize=9)
    finish(fig, ax, "How well can the next night be forecast?",
           "Share of the achievable saving a forecast-driven schedule captures, scored on what actually happened.", "forecast_quality.png")


def fig_india() -> None:
    W = R["india"]["windows"]
    es = next(s for s in R["savings"] if s["id"] == "es1518")["median_pct"]
    names = ["Spain overnight", "India overnight", "India daytime", "India afternoon"]
    vals = [es, W["overnight"]["median_cut_pct"], W["daytime"]["median_cut_pct"], W["afternoon"]["median_cut_pct"]]
    fig, ax = plt.subplots(figsize=(9, 3.6))
    fig.subplots_adjust(top=0.72, left=0.2)
    ax.barh(names[::-1], vals[::-1], color=[GREY, GREY, BLUE, GREY][::-1], height=0.6)
    for i, v in enumerate(vals[::-1]):
        ax.text(v + 0.04, i, f"{v:.2f}%", va="center", fontsize=9, color=INK2)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.1f}%")
    ax.grid(axis="y", visible=False)
    finish(fig, ax, "India: where there is a saving",
           f"Median carbon cut by charging window, {R['india']['days']} days of Grid-India data. Spain overnight for scale.", "india_windows.png")


if __name__ == "__main__":
    for f in (fig_savings, fig_hosting, fig_sensitivity, fig_forecast, fig_india):
        f()
