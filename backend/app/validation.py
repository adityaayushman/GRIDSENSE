"""Validation of the residential baseline against real smart-meter data, served from the file
`ml/validation/export.py` writes.

Spain and the UK are validated on raw household panels (GoiEner, Low Carbon London). India has no open
household data, so its entry is a published-figure check and says so (`kind: "published"`).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data" / "validation.json"


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def summary() -> dict:
    d = _data()
    return {"generated_at": d["generated_at"], "comparison": d["comparison"],
            "regions": [{"key": r["key"], "name": r["name"], "kind": r["kind"], "source": r["source"],
                         "licence": r["licence"], "homes_in_panel": r["homes_in_panel"]} for r in d["regions"]]}


def region(key: str) -> dict:
    for r in _data()["regions"]:
        if r["key"] == key:
            return r
    raise ValueError(f"no validation for {key!r}; have {[r['key'] for r in _data()['regions']]}")
