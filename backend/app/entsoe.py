"""Live carbon intensity from the ENTSO-E Transparency Platform.

This replaces a WattTime stub that pointed at North American balancing
authorities while every other series in this project is Spanish — enabling it
would have mixed continents. ENTSO-E is where the offline data came from, so the
live path and the bundled path derive intensity the same way: actual generation
per production type, weighted by IPCC AR5 lifecycle emission factors.

Requires a free security token: register at transparency.entsoe.eu, then email
transparency@entsoe.eu asking for API access (their documented process). Set it
as ENTSOE_TOKEN.

API docs: https://documenter.getpostman.com/view/7009892/2s93JtP3F6
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import httpx

API = "https://web-api.tp.entsoe.eu/api"
NS = {"ns": "urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0"}

# ENTSO-E bidding-zone EIC codes.
DOMAINS = {
    "ES": "10YES-REE------0",
    "FR": "10YFR-RTE------C",
    "DE": "10Y1001A1001A83F",
    "PT": "10YPT-REN------W",
}

# psrType -> gCO2eq/kWh, lifecycle (IPCC AR5 WG3 Annex III medians). Identical
# factors to ml/src/carbon.py, keyed by ENTSO-E's production-type codes so the
# live series is directly comparable to the bundled one.
FACTORS = {
    "B01": 230.0,   # Biomass
    "B02": 1054.0,  # Fossil brown coal / lignite
    "B03": 820.0,   # Fossil coal-derived gas
    "B04": 490.0,   # Fossil gas
    "B05": 820.0,   # Fossil hard coal
    "B06": 650.0,   # Fossil oil
    "B07": 1000.0,  # Fossil oil shale
    "B08": 1000.0,  # Fossil peat
    "B09": 38.0,    # Geothermal
    "B10": 24.0,    # Hydro pumped storage
    "B11": 24.0,    # Hydro run-of-river
    "B12": 24.0,    # Hydro water reservoir
    "B13": 17.0,    # Marine
    "B14": 12.0,    # Nuclear
    "B15": 100.0,   # Other renewable
    "B16": 45.0,    # Solar
    "B17": 700.0,   # Waste
    "B18": 11.0,    # Wind offshore
    "B19": 11.0,    # Wind onshore
    "B20": 700.0,   # Other — unspecified, assumed fossil-like
}

# Consumption filling pumped storage, not supply. Counting it would double-count,
# since it is re-served later as B10 generation.
CONSUMPTION_TYPES = {"B10"}


class EntsoeError(RuntimeError):
    pass


def _stamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M")


def parse_generation(xml: str) -> dict[int, dict[str, float]]:
    """Parse an A75 document into {hour_utc: {psrType: MW}}.

    ENTSO-E returns one TimeSeries per production type, each with its own
    resolution — 15-minute for some zones, hourly for others — so positions are
    converted to wall-clock hours rather than assumed to be hourly, and
    sub-hourly points are averaged into their hour.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise EntsoeError(f"malformed XML from ENTSO-E: {exc}") from exc

    # The document namespace carries a version that changes between revisions,
    # so match on local names instead of pinning one.
    def find_all(node, tag):
        return [e for e in node.iter() if e.tag.rsplit("}", 1)[-1] == tag]

    if find_all(root, "Reason") and not find_all(root, "TimeSeries"):
        text = " ".join(e.text or "" for e in find_all(root, "text"))
        raise EntsoeError(f"ENTSO-E returned no data: {text.strip() or 'unknown reason'}")

    buckets: dict[int, dict[str, list[float]]] = {}
    for ts in find_all(root, "TimeSeries"):
        psr = next((e.text for e in find_all(ts, "psrType")), None)
        if psr is None:
            continue
        is_consumption = bool(find_all(ts, "inBiddingZone_Domain.mRID")) is False

        for period in find_all(ts, "Period"):
            start_txt = next((e.text for e in find_all(period, "start")), None)
            res = next((e.text for e in find_all(period, "resolution")), "PT60M")
            if not start_txt:
                continue
            start = datetime.fromisoformat(start_txt.replace("Z", "+00:00"))
            step = 15 if "PT15M" in res else 30 if "PT30M" in res else 60

            for point in find_all(period, "Point"):
                pos = next((e.text for e in find_all(point, "position")), None)
                qty = next((e.text for e in find_all(point, "quantity")), None)
                if pos is None or qty is None:
                    continue
                when = start + timedelta(minutes=step * (int(pos) - 1))
                hour = when.astimezone(timezone.utc).hour
                value = float(qty)
                # Pumped-storage consumption arrives as its own TimeSeries with
                # an outBiddingZone domain; subtracting it here would understate
                # supply, so it is simply dropped.
                if psr in CONSUMPTION_TYPES and is_consumption:
                    continue
                buckets.setdefault(hour, {}).setdefault(psr, []).append(value)

    return {
        h: {p: sum(v) / len(v) for p, v in types.items() if v}
        for h, types in buckets.items()
    }


def carbon_intensity_from_generation(by_hour: dict[int, dict[str, float]]) -> list[float]:
    """Weight each hour's mix by emission factors. Missing hours interpolate."""
    out: list[float | None] = [None] * 24
    for hour, mix in by_hour.items():
        total = sum(mw for p, mw in mix.items() if p in FACTORS)
        if total <= 0:
            continue
        out[hour] = sum(mw * FACTORS[p] for p, mw in mix.items() if p in FACTORS) / total

    known = [h for h, v in enumerate(out) if v is not None]
    if not known:
        raise EntsoeError("no hour had reportable generation")
    # Carry the nearest known hour into gaps rather than dropping to zero, which
    # the optimizer would read as a perfectly clean hour and pile load into.
    for h in range(24):
        if out[h] is None:
            nearest = min(known, key=lambda k: abs(k - h))
            out[h] = out[nearest]
    return [round(float(v), 1) for v in out]  # type: ignore[arg-type]


def fetch_carbon_intensity(region: str = "ES", token: str | None = None,
                           day: datetime | None = None) -> list[float]:
    """Measured carbon intensity for `region`, gCO2eq/kWh by hour 0-23 UTC."""
    token = token or os.getenv("ENTSOE_TOKEN")
    if not token:
        raise EntsoeError("ENTSOE_TOKEN is not set")
    domain = DOMAINS.get(region.upper())
    if not domain:
        raise EntsoeError(f"unknown region {region!r}; known: {sorted(DOMAINS)}")

    day = day or datetime.now(timezone.utc) - timedelta(days=1)
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)

    resp = httpx.get(API, params={
        "securityToken": token,
        "documentType": "A75",              # actual generation per type
        "processType": "A16",               # realised
        "in_Domain": domain,
        "periodStart": _stamp(start),
        "periodEnd": _stamp(start + timedelta(days=1)),
    }, timeout=20.0)
    if resp.status_code == 401:
        raise EntsoeError("ENTSO-E rejected the token (401)")
    resp.raise_for_status()
    return carbon_intensity_from_generation(parse_generation(resp.text))
