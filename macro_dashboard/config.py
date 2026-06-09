"""
config.py
=========
Central configuration for the India Macro Intelligence Dashboard.

Everything tunable lives here: API keys, data-series identifiers, scoring
weights, thresholds, refresh cadence, and the master list of news sources.

Design notes
------------
* No secrets are hard-coded. Keys are read from environment / .env.
* Each data series is described by a `SeriesSpec` so the data layer can fetch,
  cache and synthesise it uniformly regardless of provider.
* Weights for every composite score are kept here so the methodology is
  auditable in one place (important for an investment-committee context).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # dotenv is optional
    pass


# --------------------------------------------------------------------------- #
#  Paths & runtime
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("MACRO_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# User-supplied real data drops in here as CSV (date,value) and overrides
# synthetic fallbacks automatically. e.g. data/overrides/india_gst.csv
OVERRIDE_DIR = DATA_DIR / "overrides"
OVERRIDE_DIR.mkdir(parents=True, exist_ok=True)

HISTORY_DB = DATA_DIR / "macro_history.sqlite"   # SQLite snapshot store

REFRESH_SECONDS = 15 * 60          # auto-refresh cadence (15 minutes)
CACHE_TTL_SECONDS = 15 * 60        # Streamlit cache TTL
REQUEST_TIMEOUT = 20               # seconds for any HTTP call


# --------------------------------------------------------------------------- #
#  API keys
# --------------------------------------------------------------------------- #
def _get_key(name: str) -> str:
    """
    Resolve a secret from (in order): OS env / .env  ->  Streamlit secrets.
    This makes the same code work locally (.env) and on Streamlit Community
    Cloud, where secrets are injected via st.secrets, not environment files.
    """
    val = os.getenv(name, "").strip()
    if val:
        return val
    try:
        import streamlit as st  # only available at runtime in the app

        return str(st.secrets.get(name, "")).strip()
    except Exception:
        return ""


FRED_API_KEY = _get_key("FRED_API_KEY")
NEWS_API_KEY = _get_key("NEWS_API_KEY")

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


# --------------------------------------------------------------------------- #
#  Series specification
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SeriesSpec:
    """Describes one macro time-series and how to obtain it."""
    key: str                       # internal id, also override-CSV filename
    label: str                     # human label for charts
    provider: str                  # 'fred' | 'override' | 'synthetic'
    code: str = ""                 # provider-specific code (e.g. FRED series id)
    units: str = ""                # display units
    freq: str = "M"                # pandas freq hint: D/W/M/Q
    # Synthetic generation hints (mean level, drift/yr, noise sd, optional floor)
    syn_level: float = 100.0
    syn_drift: float = 0.0
    syn_noise: float = 1.0
    syn_floor: float | None = None
    higher_is_expansion: bool = True   # direction for scoring


# --- India: rates / curve / credit ---------------------------------------- #
# FRED carries several India series; where it doesn't, we fall back to
# synthetic or to a user CSV override. FRED ids below that exist as of writing
# are marked REAL; others are placeholders the user can map to a vendor feed.
INDIA_RATES = [
    SeriesSpec("india_10y", "India 10Y G-Sec", "fred", "INDIRLTLT01STM",  # REAL (IMF/OECD via FRED)
               units="%", freq="M", syn_level=7.1, syn_noise=0.15, higher_is_expansion=False),
    SeriesSpec("india_2y", "India 2Y G-Sec", "synthetic", units="%", freq="M",
               syn_level=6.6, syn_noise=0.15, higher_is_expansion=False),
    SeriesSpec("india_1y", "India 1Y G-Sec", "synthetic", units="%", freq="M",
               syn_level=6.4, syn_noise=0.15, higher_is_expansion=False),
    SeriesSpec("india_repo", "RBI Repo Rate", "synthetic", units="%", freq="M",
               syn_level=6.5, syn_noise=0.05, higher_is_expansion=False),
]

INDIA_CREDIT = [
    SeriesSpec("india_aaa", "AAA Corp Bond Yield", "synthetic", units="%", freq="M",
               syn_level=7.7, syn_noise=0.2, higher_is_expansion=False),
    SeriesSpec("india_aa", "AA Corp Bond Yield", "synthetic", units="%", freq="M",
               syn_level=8.3, syn_noise=0.25, higher_is_expansion=False),
    SeriesSpec("india_credit_growth", "Bank Credit Growth YoY", "synthetic", units="%",
               freq="M", syn_level=14.0, syn_noise=1.0, higher_is_expansion=True),
]

# --- India: activity / demand ---------------------------------------------- #
INDIA_ACTIVITY = [
    SeriesSpec("india_pmi_mfg", "Mfg PMI", "synthetic", units="idx", freq="M",
               syn_level=55.0, syn_noise=1.5, higher_is_expansion=True),
    SeriesSpec("india_gst", "GST Collections", "override", units="₹ cr", freq="M",
               syn_level=170000, syn_drift=12000, syn_noise=6000, higher_is_expansion=True),
    SeriesSpec("india_upi_value", "UPI Value", "override", units="₹ cr", freq="M",
               syn_level=2000000, syn_drift=350000, syn_noise=60000, higher_is_expansion=True),
    SeriesSpec("india_upi_volume", "UPI Volume", "override", units="mn txns", freq="M",
               syn_level=12000, syn_drift=2200, syn_noise=400, higher_is_expansion=True),
    SeriesSpec("india_2w_sales", "2-Wheeler Sales", "override", units="units", freq="M",
               syn_level=1500000, syn_drift=40000, syn_noise=120000, higher_is_expansion=True),
    SeriesSpec("india_entry_car", "Entry Car Sales", "override", units="units", freq="M",
               syn_level=300000, syn_drift=2000, syn_noise=25000, higher_is_expansion=True),
    SeriesSpec("india_diesel", "Diesel Consumption", "override", units="kt", freq="M",
               syn_level=7000, syn_drift=180, syn_noise=300, higher_is_expansion=True),
    SeriesSpec("india_petrol", "Petrol Consumption", "override", units="kt", freq="M",
               syn_level=3200, syn_drift=200, syn_noise=150, higher_is_expansion=True),
    SeriesSpec("india_atf", "Aviation Fuel", "override", units="kt", freq="M",
               syn_level=700, syn_drift=40, syn_noise=40, higher_is_expansion=True),
    SeriesSpec("india_retail_credit", "Retail Credit Growth YoY", "synthetic", units="%",
               freq="M", syn_level=16.0, syn_noise=1.2, higher_is_expansion=True),
]

# --- India: inflation ------------------------------------------------------- #
INDIA_INFLATION = [
    SeriesSpec("india_cpi", "CPI YoY", "fred", "INDCPIALLMINMEI",  # level index; we YoY it
               units="%", freq="M", syn_level=5.0, syn_noise=0.4, higher_is_expansion=False),
    SeriesSpec("india_wpi", "WPI YoY", "synthetic", units="%", freq="M",
               syn_level=3.5, syn_noise=0.8, higher_is_expansion=False),
    SeriesSpec("india_core_cpi", "Core CPI YoY", "synthetic", units="%", freq="M",
               syn_level=4.3, syn_noise=0.3, higher_is_expansion=False),
    SeriesSpec("india_food_cpi", "Food CPI YoY", "synthetic", units="%", freq="M",
               syn_level=6.0, syn_noise=1.2, higher_is_expansion=False),
]

# --- United States ---------------------------------------------------------- #
US_SERIES = [
    SeriesSpec("us_cpi", "US CPI YoY", "fred", "CPIAUCSL", units="%", freq="M",
               syn_level=3.0, syn_noise=0.3, higher_is_expansion=False),
    SeriesSpec("us_core_cpi", "US Core CPI YoY", "fred", "CPILFESL", units="%", freq="M",
               syn_level=3.3, syn_noise=0.3, higher_is_expansion=False),
    SeriesSpec("us_ppi", "US PPI YoY", "fred", "PPIACO", units="%", freq="M",
               syn_level=2.0, syn_noise=0.5, higher_is_expansion=False),
    SeriesSpec("us_unemployment", "US Unemployment", "fred", "UNRATE", units="%", freq="M",
               syn_level=4.0, syn_noise=0.15, higher_is_expansion=False),
    SeriesSpec("us_ism_pmi", "US ISM Mfg PMI", "synthetic", units="idx", freq="M",
               syn_level=49.5, syn_noise=1.5, higher_is_expansion=True),
    SeriesSpec("us_retail", "US Retail Sales", "fred", "RSAFS", units="$mn", freq="M",
               syn_level=700000, syn_drift=20000, syn_noise=8000, higher_is_expansion=True),
    SeriesSpec("us_fedfunds", "US Fed Funds Rate", "fred", "FEDFUNDS", units="%", freq="M",
               syn_level=4.5, syn_noise=0.05, higher_is_expansion=False),
    SeriesSpec("us_10y", "US 10Y Treasury", "fred", "DGS10", units="%", freq="D",
               syn_level=4.2, syn_noise=0.1, higher_is_expansion=False),
    SeriesSpec("us_2y", "US 2Y Treasury", "fred", "DGS2", units="%", freq="D",
               syn_level=4.3, syn_noise=0.1, higher_is_expansion=False),
    SeriesSpec("vix", "VIX", "fred", "VIXCLS", units="idx", freq="D",
               syn_level=16.0, syn_noise=3.0, syn_floor=9.0, higher_is_expansion=False),
]

ALL_SERIES = (INDIA_RATES + INDIA_CREDIT + INDIA_ACTIVITY +
              INDIA_INFLATION + US_SERIES)
SERIES_BY_KEY = {s.key: s for s in ALL_SERIES}


# --------------------------------------------------------------------------- #
#  Scoring weights
# --------------------------------------------------------------------------- #
BUSINESS_CYCLE_WEIGHTS = {      # Section 1 — must sum to 1.0
    "yield_curve": 0.40,
    "credit_spreads": 0.30,
    "pmi_trend": 0.15,
    "credit_growth": 0.15,
}

CONSUMER_DEMAND_WEIGHTS = {     # Section 2 — must sum to 1.0
    "gst": 0.20,
    "upi": 0.20,
    "pmi": 0.15,
    "auto": 0.15,
    "petroleum": 0.15,
    "retail_credit": 0.15,
}

# RBI inflation target framework
RBI_TARGET = 4.0
RBI_LOWER_BAND = 2.0
RBI_UPPER_BAND = 6.0

# Score colour bands (consumer demand 0-100)
DEMAND_GREEN = 70
DEMAND_YELLOW = 50


# --------------------------------------------------------------------------- #
#  News / alert sources
# --------------------------------------------------------------------------- #
# Public RSS feeds. These are best-effort; some publishers rate-limit or
# block. NewsAPI is used as the primary aggregator when a key is present.
RSS_FEEDS = {
    "Reuters Markets": "https://www.reutersagency.com/feed/?best-topics=markets&post_type=best",
    "IMF": "https://www.imf.org/en/news/rss?Language=ENG",
    "ECB": "https://www.ecb.europa.eu/rss/press.html",
    "Fed": "https://www.federalreserve.gov/feeds/press_all.xml",
    "BIS": "https://www.bis.org/rss/cbspeeches.xml",
    "World Bank": "https://www.worldbank.org/en/news/all?format=rss",
}

# Keyword → (category, base severity 1-4) for the rule-based alert scorer.
ALERT_KEYWORDS = {
    # Geopolitical
    "war": ("Geopolitical", 4), "invasion": ("Geopolitical", 4),
    "missile": ("Geopolitical", 3), "sanction": ("Geopolitical", 3),
    "tariff": ("Geopolitical", 2), "trade war": ("Geopolitical", 3),
    "ceasefire": ("Geopolitical", 1), "conflict": ("Geopolitical", 3),
    "supply chain": ("Geopolitical", 2),
    # Financial
    "bank failure": ("Financial", 4), "bank run": ("Financial", 4),
    "default": ("Financial", 4), "sovereign": ("Financial", 3),
    "liquidity": ("Financial", 3), "currency crisis": ("Financial", 4),
    "devaluation": ("Financial", 3), "bailout": ("Financial", 3),
    "downgrade": ("Financial", 2),
    # Economic
    "recession": ("Economic", 3), "contraction": ("Economic", 2),
    "inflation": ("Economic", 2), "stagflation": ("Economic", 3),
    "gdp": ("Economic", 1), "oil price": ("Economic", 2),
    "energy crisis": ("Economic", 3), "commodity": ("Economic", 1),
    # Market
    "yield curve": ("Market", 2), "inversion": ("Market", 3),
    "credit spread": ("Market", 2), "selloff": ("Market", 2),
    "crash": ("Market", 4), "volatility": ("Market", 2),
    "circuit breaker": ("Market", 3),
}

SEVERITY_LABELS = {1: "Low", 2: "Medium", 3: "High", 4: "Critical"}
SEVERITY_COLORS = {1: "#2ecc71", 2: "#f1c40f", 3: "#e67e22", 4: "#e74c3c"}

# Risk-free rate assumption for any ratio (kept here for auditability)
RISK_FREE_RATE = 0.065
