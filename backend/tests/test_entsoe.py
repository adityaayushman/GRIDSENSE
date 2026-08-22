"""Tests for the live ENTSO-E path.

The network call itself is not exercised — it needs a token issued by ENTSO-E on
request. What is exercised is everything that can silently go wrong without one:
parsing their XML, mapping production types to emission factors, and the failure
modes that would otherwise surface as a plausible-looking but wrong curve.
"""

import pytest

from app.entsoe import (
    EntsoeError,
    carbon_intensity_from_generation,
    fetch_carbon_intensity,
    parse_generation,
)

NS = 'xmlns="urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0"'


def doc(series: str) -> str:
    return f'<GL_MarketDocument {NS}>{series}</GL_MarketDocument>'


def ts(psr: str, start: str, points: list[float], resolution: str = "PT60M") -> str:
    pts = "".join(
        f"<Point><position>{i}</position><quantity>{q}</quantity></Point>"
        for i, q in enumerate(points, 1)
    )
    return (
        f"<TimeSeries>"
        f"<inBiddingZone_Domain.mRID>10YES-REE------0</inBiddingZone_Domain.mRID>"
        f"<MktPSRType><psrType>{psr}</psrType></MktPSRType>"
        f"<Period><timeInterval><start>{start}</start></timeInterval>"
        f"<resolution>{resolution}</resolution>{pts}</Period></TimeSeries>"
    )


def test_parses_hourly_generation_by_type():
    xml = doc(ts("B16", "2024-03-01T00:00Z", [0.0, 0.0, 500.0])
              + ts("B04", "2024-03-01T00:00Z", [800.0, 800.0, 400.0]))
    got = parse_generation(xml)
    assert got[0] == {"B16": 0.0, "B04": 800.0}
    assert got[2] == {"B16": 500.0, "B04": 400.0}


def test_sub_hourly_points_average_into_their_hour():
    """Some bidding zones report 15-minute data; positions are wall-clock, not hours."""
    xml = doc(ts("B04", "2024-03-01T00:00Z", [100.0, 200.0, 300.0, 400.0], "PT15M"))
    got = parse_generation(xml)
    assert got[0]["B04"] == pytest.approx(250.0)  # mean of the four quarters
    assert len(got) == 1, "four 15-min points must land in one hour, not four"


def test_carbon_intensity_weights_the_mix():
    """All-solar reads near solar's factor; all-gas near gas's."""
    solar = carbon_intensity_from_generation({0: {"B16": 1000.0}})
    gas = carbon_intensity_from_generation({0: {"B04": 1000.0}})
    assert solar[0] == pytest.approx(45.0, rel=1e-3)
    assert gas[0] == pytest.approx(490.0, rel=1e-3)
    assert all(v == solar[0] for v in solar), "single known hour carries to the rest"


def test_mixed_hour_lands_between_its_components():
    out = carbon_intensity_from_generation({0: {"B16": 500.0, "B04": 500.0}})
    assert 45.0 < out[0] < 490.0
    assert out[0] == pytest.approx((45.0 + 490.0) / 2, rel=1e-3)


def test_gaps_carry_a_neighbour_rather_than_reading_as_clean():
    """A missing hour must never come back as 0 — the optimizer would treat that
    as perfectly clean and pile the whole fleet into it."""
    out = carbon_intensity_from_generation({6: {"B04": 1000.0}})
    assert len(out) == 24
    assert all(v > 0 for v in out)
    assert out[0] == pytest.approx(490.0, rel=1e-3)


def test_pumped_storage_consumption_is_not_counted_as_supply():
    """Consumption filling storage arrives without an inBiddingZone domain."""
    consumption = (
        "<TimeSeries>"
        "<outBiddingZone_Domain.mRID>10YES-REE------0</outBiddingZone_Domain.mRID>"
        "<MktPSRType><psrType>B10</psrType></MktPSRType>"
        "<Period><timeInterval><start>2024-03-01T00:00Z</start></timeInterval>"
        "<resolution>PT60M</resolution>"
        "<Point><position>1</position><quantity>900</quantity></Point></Period>"
        "</TimeSeries>"
    )
    got = parse_generation(doc(ts("B04", "2024-03-01T00:00Z", [100.0]) + consumption))
    assert "B10" not in got.get(0, {}), "storage consumption must not inflate supply"


def test_empty_document_raises_rather_than_returning_zeros():
    body = doc("<Reason><code>999</code><text>No matching data found</text></Reason>")
    with pytest.raises(EntsoeError, match="no data"):
        parse_generation(body)


def test_malformed_xml_raises():
    with pytest.raises(EntsoeError, match="malformed"):
        parse_generation("<GL_MarketDocument><unclosed>")


def test_no_reportable_generation_raises():
    with pytest.raises(EntsoeError, match="no hour"):
        carbon_intensity_from_generation({0: {"B99": 500.0}})  # unknown type


def test_unknown_region_is_rejected_before_any_request():
    with pytest.raises(EntsoeError, match="unknown region"):
        fetch_carbon_intensity("CAISO", token="x")


def test_missing_token_is_rejected_before_any_request(monkeypatch):
    monkeypatch.delenv("ENTSOE_TOKEN", raising=False)
    with pytest.raises(EntsoeError, match="ENTSOE_TOKEN"):
        fetch_carbon_intensity("ES")


# --- scratch-directory guard -------------------------------------------------

def test_tmpdir_prefers_a_configured_location(tmp_path, monkeypatch):
    """An override wins, so a deployment can point scratch wherever it likes."""
    from app.tmpdir import ensure_writable_tmpdir

    monkeypatch.setenv("GRIDSENSE_TMPDIR", str(tmp_path))
    assert ensure_writable_tmpdir() == str(tmp_path)
    # CBC is a subprocess, so the environment must carry it, not just tempfile.
    import os
    assert os.environ["TMPDIR"] == str(tmp_path)


def test_tmpdir_falls_back_when_no_candidate_exists(monkeypatch):
    """On a host with none of the candidates — Vercel, CI — the platform
    default is kept rather than a directory being invented."""
    import tempfile

    from app import tmpdir as mod

    monkeypatch.delenv("GRIDSENSE_TMPDIR", raising=False)
    monkeypatch.setattr(mod, "CANDIDATES", [])
    assert mod.ensure_writable_tmpdir() == str(tempfile.gettempdir())


def test_tmpdir_rejects_a_location_without_room(tmp_path, monkeypatch):
    """A candidate that exists but has no space must not be chosen."""
    from app import tmpdir as mod

    monkeypatch.delenv("GRIDSENSE_TMPDIR", raising=False)
    monkeypatch.setattr(mod, "MIN_FREE_BYTES", 1 << 62)  # nothing can satisfy this
    monkeypatch.setattr(mod, "CANDIDATES", [tmp_path])
    import tempfile
    assert mod.ensure_writable_tmpdir() == str(tempfile.gettempdir())
