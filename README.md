# 🇮🇳 India Macro Intelligence Dashboard

A modular, institutional-style macro monitoring system built in Streamlit +
Plotly. It nowcasts the **Indian business cycle**, **consumer demand**,
**inflation & RBI policy**, the **US/Fed picture**, **global risk**, and turns
all of it into a **portfolio-positioning regime** plus a downloadable
**Weekly Investment Committee PDF**.

---

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # optional: add API keys
streamlit run app.py
```

It runs **immediately with no keys** — every series falls back to a seeded,
macro-plausible synthetic generator, so the whole dashboard renders and all
engines compute. Add keys / data to make it live (see below).

---

## Architecture

| File | Responsibility |
|------|----------------|
| `config.py` | All tunables: API keys, series specs, scoring weights, thresholds, news sources. The single auditable source of methodology. |
| `data_fetcher.py` | Unified data layer (override CSV → FRED → synthetic), trend stats, SQLite snapshot store for week-over-week deltas. |
| `business_cycle_engine.py` | Section 1 — yield curve + credit spreads + PMI + credit growth → weighted phase + confidence. |
| `macro_scoring_engine.py` | Sections 2/3/4/6 — consumer demand score, inflation pack, RBI & Fed probability nowcasts, India sensitivity, portfolio regime. |
| `news_engine.py` | Section 5 source — NewsAPI + RSS aggregation with offline sample fallback. |
| `alert_engine.py` | Section 5 — keyword risk scoring + quantitative market-stress triggers → aggregate Global Risk Level. |
| `report_generator.py` | Weekly Macro Investment Committee PDF (reportlab). |
| `app.py` | Streamlit UI: CIO dashboard, gauges, heatmaps, traffic lights, tabs, auto-refresh. |

Engines have **no Streamlit dependency**, so they're independently testable and
the PDF can run on a cron schedule.

---

## Going live — data sources

**Works out of the box** via FRED (free key): US CPI/Core/PPI, unemployment,
retail sales, Fed funds, 2Y/10Y Treasuries, VIX, and India 10Y + CPI.

```
FRED_API_KEY=...   # https://fred.stlouisfed.org/docs/api/api_key.html
NEWS_API_KEY=...   # https://newsapi.org/  (RSS feeds work without this)
```

### India-specific series (GST, UPI, auto sales, fuel, PMI)
These **have no clean free public API**. The honest options:

1. **CSV override (recommended):** drop a file at
   `data/overrides/<key>.csv` with columns `date,value`. It instantly
   overrides the synthetic series — no code change.
   Keys: `india_gst`, `india_upi_value`, `india_upi_volume`,
   `india_2w_sales`, `india_entry_car`, `india_diesel`, `india_petrol`,
   `india_atf`, `india_pmi_mfg`, `india_2y`, `india_1y`, etc.
   (run the **Diagnostics** tab to see every key and its current source).
2. **Vendor feed:** point `SeriesSpec.provider`/`code` at a paid feed
   (Bloomberg, Refinitiv, CMIE, CCIL) and add a fetch branch in
   `data_fetcher.get_series`.

Sources you'd wire in for production: PIB/GSTN (GST), NPCI (UPI), SIAM &
company filings (autos), PPAC (fuel), S&P Global (PMI), CCIL (G-Sec curve),
RBI DBIE (credit growth, repo).

---

## Methodology notes (read before committee use)

- **Scoring is rule-based and transparent**, not ML black-box — every weight
  lives in `config.py`. Cycle phase blends a continuous expansion score with
  its momentum (level vs. direction) to separate e.g. *Mid* vs *Late* expansion.
- **RBI/Fed probabilities are heuristic nowcasts**, derived from inflation,
  growth, real rates and liquidity — **not** market-implied (OIS/fed-funds
  futures). Swap in market data for true market-priced odds.
- The **synthetic fallback is deterministic** (seeded per series) so numbers
  don't wander between refreshes when a source is offline.
- This is an internal monitoring tool, **not investment advice**.

---

## Refresh & history
- Auto-refresh toggle (sidebar) reruns every 15 minutes; manual refresh clears
  the cache on demand.
- Each PDF generation snapshots key metrics to `data/macro_history.sqlite`,
  enabling the **week-over-week deltas** in the next report.

---

## Deploy to Streamlit Community Cloud (free, public URL)

**Prerequisites:** a GitHub account and a Streamlit account (sign in with
GitHub at https://share.streamlit.io).

1. **Create a GitHub repo** and push this folder to it:
   ```bash
   cd macro_dashboard
   git init && git add . && git commit -m "India macro dashboard"
   git branch -M main
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```
   (The included `.gitignore` keeps secrets and the local DB out of git.)

2. **Deploy:** go to https://share.streamlit.io → **Create app** →
   **Deploy from GitHub**. Set:
   - Repository: `<you>/<repo>`
   - Branch: `main`
   - Main file path: `app.py`
   Click **Deploy**. First build takes ~2-3 min (it installs
   `requirements.txt`). You'll get a public `https://<app>.streamlit.app` URL.

3. **Add API keys (optional):** in the app's **⋮ → Settings → Secrets**, paste
   the contents of `.streamlit/secrets.toml.example` with your real keys. The
   app reads `st.secrets` automatically — no `.env` needed on Cloud. It also
   runs fine with no keys (synthetic fallback).

**Notes**
- Free tier sleeps after inactivity and wakes on the next visit (~30s cold start).
- The SQLite history DB is ephemeral on Cloud (resets on redeploy). For durable
  week-over-week history, point `HISTORY_DB` at an external store (e.g. a
  managed Postgres) — the snapshot functions in `data_fetcher.py` are the only
  place to change.
- Auto-refresh needs at least one open browser session to keep ticking.
