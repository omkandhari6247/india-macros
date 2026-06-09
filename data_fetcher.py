"""
data_fetcher.py
===============
Unified data-access layer. Every series in `config.ALL_SERIES` is fetched
through `get_series()`, which tries providers in this order:

    1. CSV override   (data/overrides/<key>.csv  with columns date,value)
    2. FRED API       (if provider == 'fred' and a key is configured)
    3. Synthetic      (deterministic, seeded, realistic-shaped fallback)

This guarantees the dashboard ALWAYS renders, while transparently using real
data wherever it is available. A SQLite store snapshots the latest reading of
every series on each run so week-over-week change detection works.

The module is import-safe (no Streamlit dependency) so the engines and unit
tests can use it directly. Streamlit-level caching is applied in app.py.
"""

from __future__ import annotations

import io
import sqlite3
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

import config


# --------------------------------------------------------------------------- #
#  Low-level providers
# --------------------------------------------------------------------------- #
def _fetch_fred(series_id: str) -> pd.Series | None:
    """Fetch a FRED series as a date-indexed float Series. None on failure."""
    if not config.FRED_API_KEY:
        return None
    try:
        params = {
            "series_id": series_id,
            "api_key": config.FRED_API_KEY,
            "file_type": "json",
            "observation_start": "2004-01-01",
        }
        r = requests.get(config.FRED_BASE, params=params,
                         timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        obs = r.json().get("observations", [])
        if not obs:
            return None
        df = pd.DataFrame(obs)
        df["date"] = pd.to_datetime(df["date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        s = df.dropna(subset=["value"]).set_index("date")["value"].sort_index()
        return s if not s.empty else None
    except Exception as exc:  # noqa: BLE001 - we want graceful degradation
        print(f"[data_fetcher] FRED fetch failed for {series_id}: {exc}")
        return None


def _fetch_override(key: str) -> pd.Series | None:
    """Load user-supplied CSV (date,value) override if present."""
    path = config.OVERRIDE_DIR / f"{key}.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
        cols = {c.lower(): c for c in df.columns}
        dcol, vcol = cols.get("date"), cols.get("value")
        if not dcol or not vcol:
            return None
        df[dcol] = pd.to_datetime(df[dcol])
        s = (df.dropna(subset=[vcol]).set_index(dcol)[vcol]
             .astype(float).sort_index())
        s.index.name = "date"
        return s if not s.empty else None
    except Exception as exc:  # noqa: BLE001
        print(f"[data_fetcher] override load failed for {key}: {exc}")
        return None


def _synthetic(spec: "config.SeriesSpec", periods: int = 180) -> pd.Series:
    """
    Deterministic, seeded synthetic series shaped to look macro-plausible:
    level + linear drift + business-cycle sinusoid + AR(1)-ish noise, with an
    optional floor. Seeded by the series key so values are stable across runs
    (important: an investment committee should not see numbers wander each
    refresh just because a source is offline).
    """
    rng = np.random.default_rng(abs(hash(spec.key)) % (2**32))
    freq = {"D": "B", "W": "W", "M": "MS", "Q": "QS"}.get(spec.freq, "MS")
    idx = pd.date_range(end=pd.Timestamp.today().normalize(),
                        periods=periods, freq=freq)

    n = len(idx)
    t = np.arange(n)
    years = (t / {"B": 252, "W": 52, "MS": 12, "QS": 4}[freq])

    drift = spec.syn_drift * years
    cycle = 0.35 * spec.syn_noise * np.sin(2 * np.pi * years / 6.0)  # ~6yr cycle
    noise = np.zeros(n)
    for i in range(1, n):                              # mild persistence
        noise[i] = 0.7 * noise[i - 1] + rng.normal(0, spec.syn_noise)

    vals = spec.syn_level + drift + cycle + noise
    if spec.syn_floor is not None:
        vals = np.maximum(vals, spec.syn_floor)
    s = pd.Series(vals, index=idx, name=spec.key)
    s.index.name = "date"
    return s


def _to_yoy(s: pd.Series) -> pd.Series:
    """Convert a monthly index level to YoY % (used for FRED CPI levels)."""
    return (s.pct_change(12) * 100).dropna()


# --------------------------------------------------------------------------- #
#  Public API
# --------------------------------------------------------------------------- #
def get_series(key: str) -> tuple[pd.Series, str]:
    """
    Return (series, source_label) for a config key.
    source_label ∈ {'override', 'fred', 'synthetic'} for UI transparency.
    """
    spec = config.SERIES_BY_KEY.get(key)
    if spec is None:
        raise KeyError(f"Unknown series key: {key}")

    s = _fetch_override(key)
    if s is not None:
        return s, "override"

    if spec.provider == "fred":
        s = _fetch_fred(spec.code)
        if s is not None:
            # FRED gives CPI as an index level; the dashboard wants YoY %.
            if key in ("india_cpi", "us_cpi", "us_core_cpi", "us_ppi"):
                s = _to_yoy(s)
            return s, "fred"

    return _synthetic(spec), "synthetic"


def get_many(keys: list[str]) -> dict[str, pd.Series]:
    """Convenience: fetch several series, dropping the source label."""
    return {k: get_series(k)[0] for k in keys}


def latest(s: pd.Series) -> float:
    """Most recent non-null value."""
    return float(s.dropna().iloc[-1]) if len(s.dropna()) else float("nan")


def trend_stats(s: pd.Series) -> dict:
    """
    Standard trend pack used across the dashboard:
    latest, MoM %, YoY %, 3M MA, 6M MA, and a slope-based direction label.
    """
    s = s.dropna()
    if s.empty:
        return {}
    cur = float(s.iloc[-1])
    mom = float(s.pct_change().iloc[-1] * 100) if len(s) > 1 else np.nan
    yoy = float(s.pct_change(12).iloc[-1] * 100) if len(s) > 12 else np.nan
    ma3 = float(s.rolling(3).mean().iloc[-1]) if len(s) >= 3 else cur
    ma6 = float(s.rolling(6).mean().iloc[-1]) if len(s) >= 6 else cur
    window = s.iloc[-6:] if len(s) >= 6 else s
    slope = float(np.polyfit(range(len(window)), window.values, 1)[0])
    direction = "Rising" if slope > 0 else "Falling" if slope < 0 else "Flat"
    return dict(latest=cur, mom=mom, yoy=yoy, ma3=ma3, ma6=ma6,
                slope=slope, direction=direction)


# --------------------------------------------------------------------------- #
#  Historical snapshot store (SQLite) — powers week-over-week comparisons
# --------------------------------------------------------------------------- #
def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(config.HISTORY_DB)
    c.execute(
        """CREATE TABLE IF NOT EXISTS snapshots (
               ts TEXT, metric TEXT, value REAL,
               PRIMARY KEY (ts, metric))"""
    )
    return c


def snapshot(metrics: dict[str, float]) -> None:
    """Persist a dict of metric→value with a UTC timestamp."""
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.executemany(
            "INSERT OR REPLACE INTO snapshots VALUES (?,?,?)",
            [(ts, k, float(v)) for k, v in metrics.items()
             if v is not None and not pd.isna(v)],
        )


def previous_snapshot(metric: str, days_ago: int = 7) -> float | None:
    """Closest stored value at least `days_ago` days old (for WoW deltas)."""
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days_ago)
    with _conn() as c:
        rows = c.execute(
            "SELECT ts, value FROM snapshots WHERE metric=? ORDER BY ts", (metric,)
        ).fetchall()
    older = [(pd.Timestamp(ts), v) for ts, v in rows if pd.Timestamp(ts) <= cutoff]
    return older[-1][1] if older else None


def data_health() -> pd.DataFrame:
    """Source-coverage table for the diagnostics panel."""
    rows = []
    for spec in config.ALL_SERIES:
        _, src = get_series(spec.key)
        rows.append({"series": spec.label, "key": spec.key,
                     "configured_provider": spec.provider, "live_source": src})
    return pd.DataFrame(rows)
