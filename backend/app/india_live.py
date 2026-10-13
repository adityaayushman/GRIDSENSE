"""Live Indian grid carbon intensity from Grid-India's own Daily PSP report.

No account, no API key, no cost. Grid-India (formerly POSOCO) publishes a daily
workbook whose `TimeSeries` sheet carries 96 fifteen-minute intervals of all-India
generation by fuel; this is the same source Electricity Maps parses for India. It is
"live" in the sense the publisher allows: the report describes the previous day and
appears on the portal the following morning, so the newest data is about a day old.
The response says which day it describes and how stale that is rather than implying
otherwise.

Columns are found by their printed header, never by position. The workbook changed
layout twice inside the archive, and an earlier positional parser read the wrong fuel
for 84% of days (FINDINGS.md finding 14). A day whose numbers are physically
implausible is refused, not served.

    GET /api/india/live
"""

from __future__ import annotations

import io
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import httpx

LIST_URL = "https://webapi.grid-india.in/api/v1/file"
CDN = "https://webcdn.grid-india.in/"
UA = "Mozilla/5.0 (compatible; GridSense/1.0; +https://github.com/adityaayushman/GRIDSENSE)"

#: gCO2eq/kWh, lifecycle, IPCC AR5 WG3 Annex III. The single THERMAL column is treated
#: as coal; it includes some lignite (1054), so this slightly understates intensity.
#: Storage discharge is excluded: its emissions belong to whatever charged it.
FACTORS = {"nuclear_mw": 12.0, "wind_mw": 11.0, "solar_mw": 45.0, "hydro_mw": 24.0,
           "gas_mw": 490.0, "thermal_mw": 820.0, "others_mw": 700.0}

LABELS = {
    "FREQUENCY": "frequency_hz", "DEMAND MET": "demand_met_mw", "STORAGE DEMAND": "storage_demand_mw",
    "NUCLEAR": "nuclear_mw", "WIND": "wind_mw", "SOLAR": "solar_mw", "HYDRO": "hydro_mw",
    "GAS": "gas_mw", "THERMAL": "thermal_mw", "STORAGE": "storage_mw", "OTHERS": "others_mw",
    "NET DEMAND MET": "net_demand_met_mw", "TOTAL GENERATION": "total_generation_mw",
}
REQUIRED = ["demand_met_mw", *FACTORS]

#: A report younger than this is "fresh"; Grid-India publishes the previous day each morning.
FRESH_DAYS = 2


class IndiaLiveError(RuntimeError):
    """The report could not be fetched or parsed into something trustworthy."""


def label_of(cell) -> str:
    """Normalise a header cell: drop the unit, footnote marks and the (A)-style code."""
    s = str(cell).split("(")[0].replace("\n", " ")
    s = "".join(ch for ch in s if ch.isalpha() or ch == " ")
    return " ".join(s.upper().split())


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_rows(rows: list[list]) -> dict[str, list[float]]:
    """Rows of the TimeSeries sheet -> {column name: 96 values}. Layout-independent."""
    head = next((i for i in range(min(10, len(rows))) if rows[i] and label_of(rows[i][0]) == "TIME"), None)
    if head is None:
        raise IndiaLiveError("no TIME header row in the TimeSeries sheet")

    cols: dict[str, int] = {}
    for idx, cell in enumerate(rows[head]):
        name = LABELS.get(label_of(cell))
        if name and name not in cols and idx > 0:
            cols[name] = idx
    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        raise IndiaLiveError(f"report is missing required columns: {missing}")

    out: dict[str, list[float]] = {name: [] for name in cols}
    for row in rows[head + 2:]:
        stamp = str(row[0]).strip() if row else ""
        if ":" not in stamp:
            continue                       # footnotes and the disclaimer
        vals = {name: _num(row[idx]) if idx < len(row) else None for name, idx in cols.items()}
        if vals["demand_met_mw"] is None:
            continue
        for name, v in vals.items():
            out[name].append(v if v is not None else float("nan"))
    n = len(out["demand_met_mw"])
    if n != 96:
        raise IndiaLiveError(f"expected 96 fifteen-minute intervals, found {n}")
    return out


def check_plausible(series: dict[str, list[float]]) -> dict:
    """Physical sanity checks. A fuel in the wrong column passes every format check."""
    solar = series["solar_mw"]
    peak = max(solar)
    night = solar[:16]                     # 00:00-03:45 IST
    solar_ok = peak < 5000 or (sum(night) / len(night)) <= 0.05 * peak
    closure_ok, gap_pct = True, None
    if "total_generation_mw" in series:
        fuels = [sum(series[f][i] for f in FACTORS) for i in range(96)]
        tot = series["total_generation_mw"]
        gaps = sorted(abs(a - b) for a, b in zip(fuels, tot))
        mean_total = sum(tot) / len(tot)
        gap_pct = round(gaps[48] / mean_total * 100, 2) if mean_total else None
        closure_ok = gap_pct is not None and gap_pct <= 2.0
    return {"solar_zero_at_night": solar_ok, "fuels_sum_to_total": closure_ok, "median_closure_gap_pct": gap_pct,
            "plausible": solar_ok and closure_ok}


def hourly(series: dict[str, list[float]]) -> dict:
    """96 fifteen-minute rows -> 24 hourly means, carbon intensity and renewable share."""
    def mean4(vals, h):
        chunk = [v for v in vals[4 * h:4 * h + 4] if v == v]
        return sum(chunk) / len(chunk) if chunk else float("nan")

    ci, demand, ren = [], [], []
    for h in range(24):
        gen = {f: mean4(series[f], h) for f in FACTORS}
        total = sum(gen.values())
        ci.append(round(sum(gen[f] * FACTORS[f] for f in FACTORS) / total, 1) if total > 0 else float("nan"))
        ren.append(round((gen["wind_mw"] + gen["solar_mw"] + gen["hydro_mw"]) / total * 100, 1) if total > 0 else float("nan"))
        demand.append(round(mean4(series["demand_met_mw"], h)))
    return {"carbon_intensity": ci, "demand_met_mw": demand, "renewable_share_pct": ren}


@dataclass
class IndiaDay:
    day: date
    carbon_intensity: list[float]
    demand_met_mw: list[int]
    renewable_share_pct: list[float]
    checks: dict
    source_file: str
    fetched_at: str
    extra: dict = field(default_factory=dict)

    def summary(self) -> dict:
        ci = self.carbon_intensity
        age = (date.today() - self.day).days
        return {
            "day": self.day.isoformat(),
            "age_days": age,
            "fresh": age <= FRESH_DAYS,
            "region": "IN",
            "timezone": "Asia/Kolkata",
            "units": {"carbon_intensity": "gCO2eq/kWh", "demand_met_mw": "MW", "renewable_share_pct": "%"},
            "hourly": [{"hour": h, "label": f"{h:02d}:00", "carbon_intensity": ci[h], "demand_met_mw": self.demand_met_mw[h],
                        "renewable_share_pct": self.renewable_share_pct[h]} for h in range(24)],
            "mean_carbon_intensity": round(sum(ci) / 24, 1),
            "cleanest_hour": min(range(24), key=ci.__getitem__),
            "dirtiest_hour": max(range(24), key=ci.__getitem__),
            "checks": self.checks,
            "source": "Grid-India Daily PSP report (TimeSeries sheet), 15-minute all-India generation by fuel",
            "source_file": self.source_file,
            "fetched_at": self.fetched_at,
            "note": "The report describes the previous day and is published the following morning, "
                    "so this is the newest data the publisher offers, not a real-time reading.",
        }


# --------------------------------------------------------------------- network
def _fiscal_year(d: date) -> str:
    start = d.year - 1 if d.month < 4 else d.year
    return f"{start}-{(start + 1) % 100:02d}"


def _listing(client: httpx.Client, d: date) -> list[tuple[date, str]]:
    r = client.post(LIST_URL, json={"_source": "GRDW", "_type": "DAILY_PSP_REPORT",
                                    "_fileDate": _fiscal_year(d), "_month": f"{d.month:02d}"})
    r.raise_for_status()
    out = []
    for row in r.json().get("retData") or []:
        mime = (row.get("MimeType") or "").lower()
        if row.get("FileType") != "DAILY_PSP_REPORT" or not ("xls" in mime or "excel" in mime):
            continue
        try:
            stamp = datetime.strptime(row["Title_"].split("_")[0], "%d.%m.%y").date()
        except (ValueError, IndexError, KeyError):
            continue
        out.append((stamp, row["FilePath"]))
    return out


def _read_sheet(content: bytes) -> list[list]:
    try:
        import xlrd
    except ImportError as e:                                   # pragma: no cover
        raise IndiaLiveError("xlrd is required to read Grid-India workbooks (pip install xlrd)") from e
    book = xlrd.open_workbook(file_contents=content)
    if "TimeSeries" not in book.sheet_names():
        raise IndiaLiveError("the report has no TimeSeries sheet")
    sh = book.sheet_by_name("TimeSeries")
    return [sh.row_values(i) for i in range(sh.nrows)]


_lock = threading.Lock()
_days: dict[date, IndiaDay] = {}
_latest: tuple[float, date, str] | None = None
LISTING_TTL_S = 20 * 60


def latest_day(now: date | None = None, client: httpx.Client | None = None) -> IndiaDay:
    """The newest published day, cached. A past day never changes, so it is cached for good;
    only the question 'is there a newer one?' expires, every twenty minutes."""
    global _latest
    now = now or date.today()
    # Answer from the cache before building an HTTP client: constructing one loads the
    # certificate bundle, which alone costs about half a second.
    with _lock:
        if _latest and time.time() - _latest[0] < LISTING_TTL_S and _latest[1] in _days:
            return _days[_latest[1]]
    own = client is None
    client = client or httpx.Client(timeout=30.0, headers={"User-Agent": UA}, follow_redirects=True)
    try:
        with _lock:
            files: list[tuple[date, str]] = []
            for back in (0, 1):                                  # this month, then the one before
                m = (now.replace(day=1) - timedelta(days=1)).replace(day=1) if back else now
                try:
                    files += _listing(client, m)
                except httpx.HTTPError as e:
                    if back == 0:
                        raise IndiaLiveError(f"Grid-India listing unreachable: {type(e).__name__}") from e
                if files:
                    break
            if not files:
                raise IndiaLiveError("Grid-India published no Daily PSP reports for this or last month")
            stamp, path = max(files)
            if stamp not in _days:
                r = client.get(CDN + path)
                r.raise_for_status()
                series = parse_rows(_read_sheet(r.content))
                checks = check_plausible(series)
                if not checks["plausible"]:
                    raise IndiaLiveError(f"the {stamp} report fails physical checks {checks}; refusing to serve it")
                _days[stamp] = IndiaDay(stamp, **hourly(series), checks=checks, source_file=path.rsplit("/", 1)[-1],
                                        fetched_at=datetime.utcnow().isoformat(timespec="seconds") + "Z")
            _latest = (time.time(), stamp, path)
            return _days[stamp]
    except httpx.HTTPError as e:
        raise IndiaLiveError(f"Grid-India request failed: {type(e).__name__}") from e
    finally:
        if own:
            client.close()
