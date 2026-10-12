"""Optional persistence of simulation runs.

Off by default. Set `DATABASE_URL` (Postgres, or any SQLAlchemy URL such as
`sqlite:///runs.db`) to record every scenario run and read them back through
`GET /api/runs`. With it unset the API behaves exactly as before and nothing here
is imported at request time.

SQLAlchemy and a database driver are deliberately not in `requirements.txt`: they
add build time to every deploy for a feature most deployments will not use. Install
`requirements-db.txt` (SQLAlchemy plus psycopg2) where persistence is wanted. If
`DATABASE_URL` is set without them, the store disables itself and says why rather
than breaking the API.

Persisting is best-effort. A database outage must never turn a successful
simulation into a 500, so a failed write is logged and dropped.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger("gridsense.store")

_engine = None
_table = None
_reason: str | None = None


def configure(url: str | None = None) -> bool:
    """(Re)connect from `url`, or from DATABASE_URL. Returns whether the store is on."""
    global _engine, _table, _reason
    _engine = _table = None
    url = url if url is not None else os.getenv("DATABASE_URL")
    if not url:
        _reason = "persistence is not configured (set DATABASE_URL)"
        return False
    try:
        import sqlalchemy as sa
        from sqlalchemy.pool import StaticPool
    except ImportError:
        _reason = "DATABASE_URL is set but SQLAlchemy is not installed (pip install -r requirements-db.txt)"
        log.warning(_reason)
        return False

    try:
        kwargs = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}} if url == "sqlite://" else {}
        engine = sa.create_engine(url, pool_pre_ping=True, **kwargs)
        meta = sa.MetaData()
        table = sa.Table(
            "scenario_runs", meta,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.String(32), nullable=False),
            sa.Column("day", sa.String(10)),
            sa.Column("objective", sa.String(16)),
            sa.Column("ev_count", sa.Integer),
            sa.Column("emissions_reduction_pct", sa.Float),
            sa.Column("cost_reduction_pct", sa.Float),
            sa.Column("peak_reduction_pct", sa.Float),
            sa.Column("request", sa.Text, nullable=False),
        )
        meta.create_all(engine)
    except Exception as e:  # driver missing, bad URL, unreachable host
        _reason = f"could not connect to the database: {type(e).__name__}"
        log.warning("%s (%s)", _reason, e)
        return False

    _engine, _table, _reason = engine, table, None
    return True


def enabled() -> bool:
    return _engine is not None


def why_disabled() -> str | None:
    return _reason


def save_run(request: dict, response: dict) -> int | None:
    """Record one run. Returns its id, or None if the store is off or the write failed."""
    if _engine is None:
        return None
    try:
        with _engine.begin() as conn:
            res = conn.execute(_table.insert().values(
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                day=response.get("day"),
                objective=request.get("objective"),
                ev_count=response.get("ev_count"),
                emissions_reduction_pct=response.get("emissions_reduction_pct"),
                cost_reduction_pct=response.get("cost_reduction_pct"),
                peak_reduction_pct=response.get("peak_reduction_pct"),
                request=json.dumps(request, default=str),
            ))
            return int(res.inserted_primary_key[0])
    except Exception as e:
        log.warning("dropping a run, write failed: %s", e)
        return None


def _row(r) -> dict:
    d = dict(r._mapping)
    d["request"] = json.loads(d["request"])
    return d


def recent(limit: int = 20) -> list[dict]:
    with _engine.connect() as conn:
        rows = conn.execute(_table.select().order_by(_table.c.id.desc()).limit(limit)).fetchall()
    return [_row(r) for r in rows]


def get(run_id: int) -> dict | None:
    with _engine.connect() as conn:
        r = conn.execute(_table.select().where(_table.c.id == run_id)).first()
    return _row(r) if r else None


# Connect once at import so a configured deployment is ready for its first request.
configure()
