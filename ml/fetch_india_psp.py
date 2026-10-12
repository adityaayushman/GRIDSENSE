"""Measured 15-minute Indian generation by fuel, from Grid-India's own reports.

Grid-India publishes a Daily PSP Report as an Excel workbook. Recent editions
carry a `TimeSeries` sheet holding **96 fifteen-minute intervals of all-India
generation split by fuel** — nuclear, wind, solar, hydro, gas, thermal, storage
and others — alongside demand met and grid frequency.

This is the primary source Electricity Maps parses for its Indian zones, so
going to it directly gives finer resolution than their hourly export and needs
no account. `india_feasibility.py` records why the *other* Grid-India products
are unusable here: the aggregate generation tables are daily, and a daily figure
has no within-night shape to schedule against. This sheet does.

Two details that would corrupt the series silently if missed:

  * The workbook is **"Report for previous day"**. A file whose sheet says
    "Date of Reporting: 23-Aug-2026" describes the 22nd, and the *filename*
    carries the data date. The filename is what this uses.
  * Values are operational SCADA telemetry, which the report's own disclaimer
    warns is subject to loss, freeze and garbage values. Nothing here is trusted
    until it has been through `screen_dataset.py`.

Downloads are cached, so re-running only fetches what is missing.

    python fetch_india_psp.py                 # default span
    python fetch_india_psp.py --from 2025-04  # explicit start
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests

try:
    # Grid-India's host omits an intermediate certificate, so certifi cannot
    # build a chain to it and every request fails verification — while curl on
    # the same machine succeeds, because the OS store already holds that
    # intermediate. truststore points Python at the same store. The wrong fix
    # here is verify=False, which would disable verification for a public
    # endpoint to work around one missing certificate.
    import truststore

    truststore.inject_into_ssl()
except ImportError:  # pragma: no cover - optional, only needed on some hosts
    pass

HERE = Path(__file__).parent
RAW = HERE / "data" / "india-psp" / "raw"
OUT = HERE / "data" / "india-grid" / "india_psp_15min.csv"

LIST_URL = "https://webapi.grid-india.in/api/v1/file"
CDN = "https://webcdn.grid-india.in/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101 Firefox/144.0"

#: Output column name for each header label in the TimeSeries sheet.
#:
#: Columns are found by their printed header, never by position. The workbook
#: layout changed twice inside the archive this reads:
#:
#:   2025-04-01 .. 2026-05-05   TIME FREQ DEMAND NUCLEAR WIND SOLAR HYDRO GAS THERMAL OTHERS ...
#:   2026-05-06 .. 2026-05-31   ... THERMAL STORAGE OTHERS ...             (storage discharge added)
#:   2026-06-01 ..              ... DEMAND STORAGE-DEMAND NUCLEAR ... THERMAL STORAGE OTHERS ...
#:
#: An earlier version of this file used one fixed positional map, correct only
#: for the last layout. For the other 425 of 508 days every fuel was read from the
#: neighbouring column - wind labelled nuclear, hydro labelled solar, coal
#: labelled gas - and the carbon intensity derived from it was wrong. See
#: FINDINGS.md finding 14.
LABELS = {
    "FREQUENCY": "frequency_hz", "DEMAND MET": "demand_met_mw",
    "STORAGE DEMAND": "storage_demand_mw", "NUCLEAR": "nuclear_mw", "WIND": "wind_mw",
    "SOLAR": "solar_mw", "HYDRO": "hydro_mw", "GAS": "gas_mw", "THERMAL": "thermal_mw",
    "STORAGE": "storage_mw", "OTHERS": "others_mw",
    "NET DEMAND MET": "net_demand_met_mw", "TOTAL GENERATION": "total_generation_mw",
    "NET TRANSNATIONAL EXCHANGE": "net_exchange_mw",
}
REQUIRED = ["frequency_hz", "demand_met_mw", "nuclear_mw", "wind_mw", "solar_mw",
            "hydro_mw", "gas_mw", "thermal_mw", "others_mw"]

#: The sheet only appears in reports from roughly April 2025 onward; earlier
#: workbooks carry MOP_E and IR-Line alone.
DEFAULT_START = "2025-04"


def fiscal_year(d: date) -> str:
    """Grid-India files by Indian fiscal year, April N to March N+1."""
    start = d.year - 1 if d.month < 4 else d.year
    return f"{start}-{(start + 1) % 100:02d}"


def month_listing(session: requests.Session, d: date) -> list[dict]:
    payload = {"_source": "GRDW", "_type": "DAILY_PSP_REPORT",
               "_fileDate": fiscal_year(d), "_month": f"{d.month:02d}"}
    r = session.post(LIST_URL, json=payload,
                     headers={"User-Agent": UA, "Content-Type": "application/json"},
                     timeout=60)
    r.raise_for_status()
    return r.json().get("retData") or []


def spreadsheets(rows: list[dict]) -> list[tuple[date, str]]:
    """(data date, path) for every Excel PSP report in a listing."""
    out = []
    for row in rows:
        if row.get("FileType") != "DAILY_PSP_REPORT":
            continue
        # The archive uses two spellings for the same workbook — older entries
        # say "attachment/xls", newer ones "application/vnd.ms-excel". Matching
        # only the substring "xls" silently discards every recent month, which
        # looks exactly like the data not existing.
        mime = (row.get("MimeType") or "").lower()
        if not ("xls" in mime or "excel" in mime):
            continue
        try:
            # Title_ leads with the date the data describes, e.g. "22.08.26_NLDC_PSP".
            stamp = datetime.strptime(row["Title_"].split("_")[0], "%d.%m.%y").date()
        except (ValueError, IndexError, KeyError):
            continue
        out.append((stamp, row["FilePath"]))
    return out


def download(session: requests.Session, day: date, path: str) -> Path | None:
    local = RAW / f"{day:%Y-%m-%d}.xls"
    if local.exists() and local.stat().st_size > 0:
        return local
    try:
        r = session.get(CDN + path, headers={"User-Agent": UA}, timeout=120)
        r.raise_for_status()
    except requests.RequestException:
        return None
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(r.content)
    time.sleep(0.4)  # the archive is a courtesy; do not hammer it
    return local


def label_of(cell) -> str:
    """Normalise a header cell: drop the unit, footnote marks and the (A)-style code."""
    # Names can wrap onto a second line ("DEMAND\nMET"), so take everything up to
    # the unit's opening bracket rather than the first line.
    s = str(cell).split("(")[0].replace("\n", " ")
    s = "".join(ch for ch in s if ch.isalpha() or ch == " ")   # footnote digits / * / superscripts
    return " ".join(s.upper().split())


def plausible(frame: pd.DataFrame) -> bool:
    """Physical sanity checks on one day's rows. A fuel in the wrong column passes every
    format check; it does not pass these.

      * solar cannot generate at night (finding 14: "solar" held 15 GW at midnight);
      * the fuels must add up to the sheet's own total generation, when it has one.
    """
    solar = frame["solar_mw"]
    if solar.max() > 5000:
        night = frame[frame["timestamp"].dt.hour < 4]["solar_mw"]
        if len(night) and night.mean() > 0.05 * solar.max():
            return False
    if "total_generation_mw" in frame.columns:
        fuels = frame[["nuclear_mw", "wind_mw", "solar_mw", "hydro_mw", "gas_mw", "thermal_mw", "others_mw"]].sum(axis=1)
        gap = (fuels - frame["total_generation_mw"]).abs().median()
        if frame["total_generation_mw"].mean() > 0 and gap > 0.02 * frame["total_generation_mw"].mean():
            return False
    return True


def parse(local: Path, day: date) -> pd.DataFrame | None:
    """The TimeSeries sheet as tidy 15-minute rows, or None if unusable."""
    try:
        book = pd.ExcelFile(local)
    except Exception:
        return None
    if "TimeSeries" not in book.sheet_names:
        return None

    raw = pd.read_excel(book, "TimeSeries", header=None)
    head = next((i for i in range(min(10, len(raw))) if label_of(raw.iat[i, 0]) == "TIME"), None)
    if head is None:
        return None

    # Map each header to its column by name. Duplicated or unknown labels are
    # ignored; a missing required fuel makes the whole file unusable rather than
    # silently filled, since a wrong fuel mix is worse than a missing day.
    cols: dict[str, int] = {}
    for idx in range(1, raw.shape[1]):
        name = LABELS.get(label_of(raw.iat[head, idx]))
        if name and name not in cols:
            cols[name] = idx
    if any(c not in cols for c in REQUIRED):
        return None

    # Data starts below the letter-code row; trailing rows are footnotes.
    body = raw.iloc[head + 2:].copy()
    frame = pd.DataFrame({name: body.iloc[:, idx] for name, idx in cols.items()})
    stamps = pd.to_datetime(body.iloc[:, 0].astype(str).str.strip(), format="%H:%M", errors="coerce")
    frame = frame[stamps.notna().values].copy()
    if frame.empty:
        return None

    stamps = stamps[stamps.notna()]
    frame["timestamp"] = [datetime.combine(day, t.time()) for t in stamps]
    for c in frame.columns:
        if c != "timestamp":
            frame[c] = pd.to_numeric(frame[c], errors="coerce")
    frame = frame.dropna(subset=["demand_met_mw"])
    return frame if plausible(frame) else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default=DEFAULT_START,
                    help="first month, YYYY-MM")
    ap.add_argument("--to", dest="end", default=None, help="last month, YYYY-MM")
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m").date().replace(day=1)
    end = (datetime.strptime(args.end, "%Y-%m").date().replace(day=1)
           if args.end else date.today().replace(day=1))

    session = requests.Session()
    months: list[date] = []
    cur = start
    while cur <= end:
        months.append(cur)
        cur = (cur.replace(day=28) + pd.Timedelta(days=7)).replace(day=1)

    frames, seen, missing, unreadable = [], set(), 0, 0
    for m in months:
        try:
            listing = month_listing(session, m)
        except requests.RequestException as e:
            print(f"  {m:%Y-%m}  listing failed ({type(e).__name__})")
            continue
        files = spreadsheets(listing)
        got = 0
        for day, path in sorted(files):
            if day in seen:
                continue
            local = download(session, day, path)
            if local is None:
                missing += 1
                continue
            df = parse(local, day)
            if df is None:
                unreadable += 1
                continue
            frames.append(df)
            seen.add(day)
            got += 1
        print(f"  {m:%Y-%m}  {got:>3} days with a TimeSeries sheet "
              f"(of {len(files)} workbooks)", flush=True)

    if not frames:
        print("\nnothing parsed — the sheet may have moved or the archive is unreachable")
        return

    all_rows = pd.concat(frames).sort_values("timestamp").reset_index(drop=True)
    all_rows = all_rows.drop_duplicates(subset=["timestamp"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    all_rows.to_csv(OUT, index=False)

    span = f"{all_rows.timestamp.min():%Y-%m-%d} -> {all_rows.timestamp.max():%Y-%m-%d}"
    print(f"\n{len(all_rows):,} fifteen-minute rows across {len(seen)} days · {span}")
    print(f"  skipped: {missing} undownloadable, {unreadable} without a usable sheet")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
