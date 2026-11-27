"""Generates the result figures for gridsense-ieee.tex from the project's own
artifact JSON/CSV files. Re-run after any of those files change:

    ../ml/venv/Scripts/python.exe make_figures.py

Figures are saved as vector PDF into ../figures/.
"""

import csv
import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

matplotlib.rcParams.update(
    {
        "font.family": "serif",
        "font.size": 9,
        "axes.edgecolor": "#444444",
        "axes.labelcolor": "#222222",
        "text.color": "#222222",
        "xtick.color": "#444444",
        "ytick.color": "#444444",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "svg.fonttype": "none",
    }
)

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parents[1] / "figures"
OUT.mkdir(exist_ok=True)

# Muted, colorblind-safe palette (consistent across figures).
BLUE = "#3C6E96"
ORANGE = "#C97A3D"
GRAY = "#8C8C8C"
DARKGRAY = "#4D4D4D"
RED = "#B4454A"


def savefig(fig, name):
    fig.tight_layout()
    fig.savefig(OUT / f"{name}.pdf")
    plt.close(fig)
    print(f"wrote {name}.pdf")


# ---------------------------------------------------------------------------
# Fig: nightly CO2 reduction distribution (finding 2)
# ---------------------------------------------------------------------------
cuts = []
with open(ROOT / "ml/data/backtest_nightly.csv", newline="", encoding="utf-8") as f:
    r = csv.DictReader(f)
    for row in r:
        cuts.append(float(row["cut_pct"]))
cuts = np.array(cuts)

fig, ax = plt.subplots(figsize=(3.4, 2.3))
bins = np.arange(-10, 32, 2)
ax.hist(cuts, bins=bins, color=BLUE, edgecolor="white", linewidth=0.4)
median = np.median(cuts)
ax.axvline(median, color=RED, linewidth=1.1, linestyle="--")
ax.text(median + 0.8, ax.get_ylim()[1] * 0.88, f"median {median:.1f}%", color=RED, fontsize=7.5)
ax.set_xlabel("CO$_2$ reduction vs. charging on arrival (%)")
ax.set_ylabel("Nights")
savefig(fig, "backtest_distribution")

# ---------------------------------------------------------------------------
# Fig: hosting capacity vs. transformer rating (finding 1)
# ---------------------------------------------------------------------------
hosting = json.load(open(ROOT / "frontend/src/data/hosting.json", encoding="utf-8"))
rows = hosting["realistic"]
ratings = [r["rating_kw"] for r in rows]
dumb = [r["dumb"] for r in rows]
coord = [r["coordinated"] for r in rows]
gain = [r["gain"] for r in rows]

fig, ax = plt.subplots(figsize=(3.4, 2.4))
x = np.arange(len(ratings))
w = 0.34
ax.bar(x - w / 2, dumb, width=w, color=GRAY, label="Charging on arrival")
ax.bar(x + w / 2, coord, width=w, color=BLUE, label="Coordinated (LP)")
for i, g in enumerate(gain):
    ax.text(x[i], max(dumb[i], coord[i]) + 20, f"{g}$\\times$", ha="center", fontsize=7.5, color=DARKGRAY)
ax.set_xticks(x)
ax.set_xticklabels([f"{r} kW" for r in ratings])
ax.set_ylabel("Vehicles hosted (median)")
ax.legend(frameon=False, fontsize=7.5, loc="upper left")
savefig(fig, "hosting_capacity")

# ---------------------------------------------------------------------------
# Fig: forecast gate sweep (finding 13) -- values transcribed from the
# verified table in FINDINGS.md s13 (ml/spread_gate.py, Spain, 361 nights).
# ---------------------------------------------------------------------------
tau = [0, 1, 2, 3, 4, 5, 7.5, 15]
saving = [5.37, 5.48, 5.58, 5.67, 5.74, 5.65, 5.29, 3.53]
worse = [26.6, 15.2, 11.9, 9.7, 7.8, 5.0, 3.6, 1.1]

fig, ax1 = plt.subplots(figsize=(3.4, 2.4))
ax1.plot(tau, saving, color=BLUE, marker="o", markersize=3, linewidth=1.3, label="Fleet-total saving")
ax1.set_xlabel(r"Gate threshold $\tau$ (expected saving, %)")
ax1.set_ylabel("Fleet-total saving (%)", color=BLUE)
ax1.tick_params(axis="y", labelcolor=BLUE)
ax1.axvline(4, color=DARKGRAY, linewidth=0.8, linestyle=":")

ax2 = ax1.twinx()
ax2.plot(tau, worse, color=ORANGE, marker="s", markersize=3, linewidth=1.3, label="Nights worse than nothing")
ax2.set_ylabel("Nights worse than nothing (%)", color=ORANGE)
ax2.tick_params(axis="y", labelcolor=ORANGE)
ax2.spines["top"].set_visible(False)
savefig(fig, "forecast_gate")

# ---------------------------------------------------------------------------
# Fig: static vs. rolling overload probability (findings 23-24)
# ---------------------------------------------------------------------------
intraday = json.load(open(ROOT / "ml/artifacts/india_robustness_intraday.json", encoding="utf-8"))
rows = [r for r in intraday["rows"] if r["error_sd_pct"] > 0 and r["margin_pct"] > 0]
labels = [f"{r['error_sd_pct']}%,{r['margin_pct']}%" for r in rows]
static = [r["static_overload_prob"] * 100 for r in rows]
rolling = [r["rolling_overload_prob"] * 100 for r in rows]

fig, ax = plt.subplots(figsize=(7.0, 2.5))
x = np.arange(len(rows))
w = 0.36
ax.bar(x - w / 2, static, width=w, color=BLUE, label="Static (commit once)")
ax.bar(x + w / 2, rolling, width=w, color=ORANGE, label="Rolling (re-forecast hourly)")
ax.axhline(5, color=RED, linewidth=0.8, linestyle="--")
ax.text(len(rows) - 0.6, 7, "5% target", color=RED, fontsize=7)
ax.set_xticks(x)
ax.set_xticklabels(labels, fontsize=7)
ax.set_xlabel(r"Forecast error $\sigma$ (%), margin (%)")
ax.set_ylabel("Overload probability (%)")
ax.legend(frameon=False, fontsize=7.5, loc="upper left")
savefig(fig, "intraday_overload")

print("done")
