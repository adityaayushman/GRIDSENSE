"""Assemble the validation results into one file for the API and the dashboard.

    python export.py          # -> frontend/src/data/validation.json, backend/app/data/validation.json

Reads what `baselines.py`, `hosting.py` and `india.py` wrote under artifacts/. Nothing is computed here
beyond arranging and a handful of derived comparison fields, so every figure traces to a script.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
ART = HERE.parent / "artifacts"
OUTS = [HERE.parent.parent / "frontend" / "src" / "data" / "validation.json",
        HERE.parent.parent / "backend" / "app" / "data" / "validation.json"]


def jload(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def hosting_rows(region: str) -> list[dict]:
    d = jload(ART / f"validation_hosting_{region}.json")["rows"]
    rows = []
    for key in ("p10_winter", "median_winter", "p90_winter", "p10_annual", "median_annual", "p90_annual"):
        if key not in d:
            continue
        r = d[key]
        rows.append({
            "key": key, "street": r["street"], "form": r["form"],
            "peak_kw_per_home": r["street_peak_kw_per_home"], "peak_hour": r["street_peak_hour"],
            "peak_to_trough": r["street_peak_to_trough"],
            "dumb": r["dumb_fine"], "coordinated": r["coordinated"], "gain": r["gain_fine"],
        })
    return rows


def european(region: str, sens: dict) -> dict:
    b = jload(ART / f"validation_baselines_{region}.json")
    rows = hosting_rows(region)
    winter = [r for r in rows if r["form"] == "winter"]
    base = sens["rows"]["base"]
    seeds = [v["gain"] for v in sens["rows"].values() if v["group"] in ("base", "noise")]
    med = next(r for r in rows if r["key"] == "median_winter")
    return {
        "key": region, "name": b["name"], "kind": "raw",
        "source": b["source"], "licence": b["licence"], "homes_in_panel": b["homes_in_panel"],
        "street_homes": b["street_homes"],
        "baseline": {
            "stats": b["stats"], "model": {k: v for k, v in b["model"].items() if k != "profile_kw"},
            "profiles": {"real_winter": b["streets"]["median"]["winter"]["profile_kw"],
                         "real_annual": b["streets"]["median"]["annual"]["profile_kw"],
                         "model": b["model"]["profile_kw"]},
            "diversity": b["diversity_winter_peak"],
        },
        "hosting": {
            "rating_kw": sens["rating_kw"], "rows": rows,
            "model": {"dumb": base["dumb_fine"], "coordinated": base["coordinated"], "gain": base["gain_fine"],
                      "noise_band": [min(seeds), max(seeds)], "noise_median": round(statistics.median(seeds), 2)},
            "median_street": {"dumb": med["dumb"], "coordinated": med["coordinated"], "gain": med["gain"]},
            "winter_gain_range": [min(r["gain"] for r in winter), max(r["gain"] for r in winter)],
        },
    }


def india() -> dict:
    d = jload(ART / "validation_india.json")
    model = d["rows"][0]
    return {
        "key": "india", "name": "India", "kind": "published",
        "source": d["published"]["source"], "url": d["published"]["url"],
        "licence": "published figure only; raw data not public", "homes_in_panel": d["published"]["households_metered"],
        "street_homes": d["homes"],
        "published": d["published"],
        "hosting": {"rating_kva": d["rating_kva"], "rows": d["rows"],
                    "model": {"dumb": model["dumb"], "coordinated": model["coordinated"], "gain": model["gain"]},
                    "published_gain_range": [min(r["gain"] for r in d["rows"][1:]), max(r["gain"] for r in d["rows"][1:])]},
    }


def main() -> None:
    sens = jload(ART / "sensitivity_hosting.json")
    regions = [european("spain", sens), european("uk", sens), india()]
    comparison = []
    for r in regions:
        h = r["hosting"]
        if r["kind"] == "raw":
            s = r["baseline"]["stats"]
            comparison.append({
                "key": r["key"], "name": r["name"], "kind": r["kind"],
                "real_peak_kw_per_home": s["peak_kw_per_home_winter"]["median"],
                "real_peak_hour": s["peak_hour_winter_mode"],
                "model_peak_kw_per_home": r["baseline"]["model"]["peak_kw_per_home"],
                "model_peak_hour": r["baseline"]["model"]["peak_hour"],
                "model_gain": h["model"]["gain"], "real_gain": h["median_street"]["gain"],
                "model_dumb": h["model"]["dumb"], "real_dumb": h["median_street"]["dumb"],
                "model_coordinated": h["model"]["coordinated"], "real_coordinated": h["median_street"]["coordinated"],
            })
        else:
            mid = h["rows"][2]
            comparison.append({
                "key": r["key"], "name": r["name"], "kind": r["kind"],
                "real_peak_kw_per_home": mid["peak_kw_per_home"], "real_peak_hour": r["published"]["peak_hour"],
                "model_peak_kw_per_home": h["rows"][0]["peak_kw_per_home"], "model_peak_hour": h["rows"][0]["peak_hour"],
                "model_gain": h["model"]["gain"], "real_gain": mid["gain"],
                "model_dumb": h["model"]["dumb"], "real_dumb": mid["dumb"],
                "model_coordinated": h["model"]["coordinated"], "real_coordinated": mid["coordinated"],
            })
    out = {"note": "Generated by ml/validation/export.py - do not edit by hand.",
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "regions": regions, "comparison": comparison}
    text = json.dumps(out, indent=1)
    for p in OUTS:
        p.write_text(text, encoding="utf-8")
    for c in comparison:
        print(f"{c['name']:<36} peak {c['model_peak_kw_per_home']}@{c['model_peak_hour']}h (model) vs "
              f"{c['real_peak_kw_per_home']}@{c['real_peak_hour']}h (real) · gain {c['model_gain']}x -> {c['real_gain']}x")


if __name__ == "__main__":
    main()
