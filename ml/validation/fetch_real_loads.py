"""Real household electricity demand, for validating the residential baseline.

The hosting-capacity headline (finding 1) rests on a modelled residential baseline: system load scaled
to a street. This turns two public smart-meter datasets into hourly kW per home so the baseline can be
checked against what real households do.

    UK     Low Carbon London, UK Power Networks. 2013, flat-tariff homes. CC BY 4.0.
           https://data.london.gov.uk/dataset/smartmeter-energy-use-data-in-london-households
    Spain  GoiEner, Basque Country and Navarre. Hourly, pre-2020, residential, no self-generation. CC BY 4.0.
           https://zenodo.org/records/7362094

Both are downloaded by hand or by the commands below into `ml/data/validation/raw/`, never run, and read
only through this script (zip and tar members are parsed as CSV text, nothing is executed or extracted
to disk). Output is `ml/data/validation/<region>_homes.npz`: kW per home per hour, the hour stamps (UTC),
and the home ids, which are the datasets' own anonymised ids.

    python fetch_real_loads.py uk
    python fetch_real_loads.py spain

India has no open household smart-meter data, so it is not here: see `build_baselines.py`.
"""

from __future__ import annotations

import io
import sys
import tarfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
DATA = HERE.parent / "data" / "validation"
RAW = DATA / "raw"
LCL_ZIP = RAW / "lcl_partitioned.zip"
GOI_TAR = RAW / "goiener_imp-pre.tzst"
GOI_META = RAW / "goiener_metadata.csv"

MIN_COVERAGE = 0.97     # a home must have this share of the year's hours to count


def uk() -> None:
    """Low Carbon London: 2013, flat-tariff homes, half-hourly kWh summed to hourly kW."""
    if not LCL_ZIP.exists():
        sys.exit(f"missing {LCL_ZIP}: download 'Partitioned LCL Data.zip' from the London Datastore page above")
    hours = pd.date_range("2013-01-01", "2013-12-31 23:00", freq="h")
    pos = {t: i for i, t in enumerate(hours)}
    homes: dict[str, np.ndarray] = {}
    z = zipfile.ZipFile(LCL_ZIP)
    members = [n for n in z.namelist() if n.endswith(".csv")]
    for k, name in enumerate(members):
        with z.open(name) as fh:
            d = pd.read_csv(fh, usecols=[0, 1, 2, 3], names=["id", "tariff", "t", "kwh"], header=0,
                            dtype={"id": "string", "tariff": "string", "t": "string", "kwh": "string"})
        d = d[(d["tariff"].str.strip() == "Std") & d["t"].str.startswith("2013")]
        if d.empty:
            continue
        d["kwh"] = pd.to_numeric(d["kwh"].str.strip(), errors="coerce")
        d = d.dropna(subset=["kwh"])
        d["h"] = pd.to_datetime(d["t"].str.slice(0, 13) + ":00:00", errors="coerce")
        g = d.groupby(["id", "h"])["kwh"].agg(["sum", "count"]).reset_index()
        g = g[g["count"] == 2]                          # both half-hours present
        for hid, sub in g.groupby("id"):
            arr = homes.setdefault(hid, np.full(len(hours), np.nan, dtype=np.float32))
            idx = sub["h"].map(pos).to_numpy()
            ok = ~pd.isna(idx)
            arr[idx[ok].astype(int)] = sub["sum"].to_numpy()[ok]       # kWh in an hour = mean kW
        print(f"  {k + 1}/{len(members)} {name.split('/')[-1]} · {len(homes)} homes", flush=True)
    keep = {h: a for h, a in homes.items() if np.isfinite(a).mean() >= MIN_COVERAGE}
    ids = sorted(keep)
    mat = np.stack([keep[i] for i in ids])
    out = DATA / "uk_homes.npz"
    np.savez_compressed(out, kw=mat, hours=hours.values.astype("datetime64[h]").astype(np.int64), ids=np.array(ids))
    print(f"wrote {out}: {mat.shape[0]} homes x {mat.shape[1]} hours ({len(homes) - len(keep)} dropped for coverage)")


def spain() -> None:
    """GoiEner: residential (CNAE 9820/9810), no self-generation, 2018, hourly kWh."""
    import zstandard

    for p in (GOI_TAR, GOI_META):
        if not p.exists():
            sys.exit(f"missing {p}: download from the Zenodo record above")
    meta = pd.read_csv(GOI_META, dtype={"cnae": "string"})
    ok = meta[meta["cnae"].isin(["9820", "9810"]) & meta["self_consumption_type"].isna()]
    ok = ok[ok["length_years"] >= 1.0]
    want = set(ok["user"])
    hours = pd.date_range("2018-01-01", "2018-12-31 23:00", freq="h", tz="UTC")     # one full pre-COVID year
    pos = {t: i for i, t in enumerate(hours)}
    homes: dict[str, np.ndarray] = {}
    with open(GOI_TAR, "rb") as fh:
        reader = zstandard.ZstdDecompressor().stream_reader(fh)
        with tarfile.open(fileobj=reader, mode="r|") as tar:
            for member in tar:
                if not member.isfile() or not member.name.endswith(".csv"):
                    continue
                uid = Path(member.name).stem
                if uid not in want:
                    continue
                d = pd.read_csv(io.BytesIO(tar.extractfile(member).read()))
                tcol = next(c for c in d.columns if "time" in c.lower() or "date" in c.lower())
                vcol = next(c for c in d.columns if "kwh" in c.lower() or "import" in c.lower())
                t = pd.to_datetime(d[tcol], utc=True, errors="coerce")
                v = pd.to_numeric(d[vcol], errors="coerce")
                arr = np.full(len(hours), np.nan, dtype=np.float32)
                idx = t.map(pos)
                good = idx.notna() & v.notna()
                arr[idx[good].astype(int).to_numpy()] = v[good].to_numpy()
                if np.isfinite(arr).mean() >= MIN_COVERAGE:
                    homes[uid] = arr
                if len(homes) % 250 == 0 and homes:
                    print(f"  {len(homes)} homes kept", flush=True)
    ids = sorted(homes)
    mat = np.stack([homes[i] for i in ids])
    out = DATA / "spain_homes.npz"
    np.savez_compressed(out, kw=mat, hours=hours.tz_convert(None).values.astype("datetime64[h]").astype(np.int64),
                        ids=np.array(ids))
    print(f"wrote {out}: {mat.shape[0]} homes x {mat.shape[1]} hours")


if __name__ == "__main__":
    DATA.mkdir(parents=True, exist_ok=True)
    {"uk": uk, "spain": spain}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit(__doc__))()
