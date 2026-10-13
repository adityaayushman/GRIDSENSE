"""Store the newest complete Indian grid day for the API to fall back on.

`GET /api/india/live` reads Grid-India's portal. If the portal cannot be reached from
wherever the API runs (Indian government hosts sometimes refuse overseas cloud
addresses), the endpoint serves the last day stored here, clearly marked as not live,
instead of failing. Refresh it whenever the PSP archive is refreshed:

    python fetch_india_psp.py
    python export_india_latest.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "backend"))

from app import india_live  # noqa: E402

CSV = HERE / "data" / "india-grid" / "india_psp_15min.csv"
OUT = HERE.parent / "backend" / "app" / "data" / "india_latest.json"

COLUMNS = ["demand_met_mw", *india_live.FACTORS, "total_generation_mw"]


def main() -> None:
    d = pd.read_csv(CSV, parse_dates=["timestamp"]).sort_values("timestamp")
    d["day"] = d["timestamp"].dt.date
    full = d.groupby("day").size()
    day = full[full == 96].index.max()
    g = d[d["day"] == day].sort_values("timestamp")
    series = {c: [float(v) for v in g[c]] for c in COLUMNS if c in g.columns}
    checks = india_live.check_plausible(series)
    if not checks["plausible"]:
        raise SystemExit(f"{day} fails the physical checks {checks}; not storing it")
    payload = {
        "day": day.isoformat(),
        **india_live.hourly(series),
        "checks": checks,
        "source_file": f"{day:%Y-%m-%d}.xls (stored copy)",
        "stored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    OUT.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"stored {day} · mean {sum(payload['carbon_intensity']) / 24:.1f} g/kWh · wrote {OUT}")


if __name__ == "__main__":
    main()
