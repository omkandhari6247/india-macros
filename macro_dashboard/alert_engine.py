"""
alert_engine.py
===============
Section 5 — Global Risk Alert System.

Two inputs feed the risk picture:

  1. Headline scoring — keyword rules (config.ALERT_KEYWORDS) classify each
     headline into a category (Geopolitical/Financial/Economic/Market) and a
     base severity 1-4. Multiple keyword hits escalate severity.

  2. Market-stress overlay — quantitative triggers from live series:
        * yield-curve inversion (US 10Y-2Y, India 10Y-2Y)
        * VIX spike (level + momentum)
        * credit-spread blow-out (India AAA over G-Sec)
     Each contributes a system-level alert independent of the news flow.

The engine returns individual alerts (title, summary, why-it-matters, impact
map across India/Equities/Bonds/INR/Commodities) plus an aggregate
'Global Risk Level' used by the portfolio engine.
"""

from __future__ import annotations

import numpy as np

import config
import data_fetcher as dfetch
import news_engine


# --------------------------------------------------------------------------- #
#  Impact templates by category — concise, committee-ready commentary
# --------------------------------------------------------------------------- #
_IMPACT = {
    "Geopolitical": {
        "India": "Higher import/energy bill, risk-off FII flows.",
        "Equities": "Negative — risk premium rises.",
        "Bonds": "Mixed — flight to quality vs. fiscal/inflation risk.",
        "INR": "Pressured via oil and risk-off.",
        "Commodities": "Higher — energy and safe-haven metals bid.",
    },
    "Financial": {
        "India": "Contagion/liquidity risk; funding-cost pressure.",
        "Equities": "Negative — financials and leverage exposed.",
        "Bonds": "Flight to quality lowers core yields; spreads widen.",
        "INR": "Volatile — depends on USD funding stress.",
        "Commodities": "Mixed — gold bid, growth-sensitive metals soft.",
    },
    "Economic": {
        "India": "Growth and earnings revisions; trade-channel impact.",
        "Equities": "Negative for cyclicals; defensives relatively resilient.",
        "Bonds": "Bullish if growth fears dominate inflation.",
        "INR": "Depends on terms-of-trade and rate differentials.",
        "Commodities": "Direction depends on demand vs. supply shock.",
    },
    "Market": {
        "India": "Spillover via global beta and FII positioning.",
        "Equities": "Negative — volatility and de-risking.",
        "Bonds": "Curve and spread dislocations possible.",
        "INR": "Volatile in risk-off episodes.",
        "Commodities": "Volatile; safe havens outperform.",
    },
}


def _score_headline(item: dict) -> dict | None:
    text = f"{item.get('title','')} {item.get('summary','')}".lower()
    hits = [(cat, sev) for kw, (cat, sev) in config.ALERT_KEYWORDS.items()
            if kw in text]
    if not hits:
        return None
    # Category = the one with the highest single severity; escalate by count.
    top_cat, top_sev = max(hits, key=lambda x: x[1])
    severity = min(4, top_sev + (1 if len(hits) >= 3 else 0))
    return {
        "title": item.get("title", "(untitled)"),
        "summary": (item.get("summary") or "")[:280],
        "category": top_cat,
        "severity": severity,
        "severity_label": config.SEVERITY_LABELS[severity],
        "source": item.get("source", ""),
        "url": item.get("url", ""),
        "why": f"Flagged on {', '.join(sorted({k for k, _ in hits}))} signals.",
        "impact": _IMPACT[top_cat],
    }


# --------------------------------------------------------------------------- #
#  Quantitative market-stress triggers
# --------------------------------------------------------------------------- #
def _market_stress_alerts() -> list[dict]:
    alerts = []

    # US curve inversion
    us10 = dfetch.latest(dfetch.get_series("us_10y")[0])
    us2 = dfetch.latest(dfetch.get_series("us_2y")[0])
    if us10 - us2 < 0:
        alerts.append(_sys_alert(
            "US Treasury curve inverted (10Y-2Y)", "Market", 3,
            f"10Y-2Y at {us10 - us2:+.2f}%. Inversions have historically led recessions.",
        ))

    # India curve inversion
    in10 = dfetch.latest(dfetch.get_series("india_10y")[0])
    in2 = dfetch.latest(dfetch.get_series("india_2y")[0])
    if in10 - in2 < 0:
        alerts.append(_sys_alert(
            "India G-Sec curve flat/inverted (10Y-2Y)", "Market", 2,
            f"10Y-2Y at {in10 - in2:+.2f}%. Signals tightening financial conditions.",
        ))

    # VIX spike
    vix = dfetch.get_series("vix")[0]
    vix_st = dfetch.trend_stats(vix)
    if vix_st.get("latest", 0) > 25:
        sev = 4 if vix_st["latest"] > 35 else 3
        alerts.append(_sys_alert(
            f"Volatility spike — VIX at {vix_st['latest']:.0f}", "Market", sev,
            "Elevated implied volatility signals risk-off and hedging demand.",
        ))

    # Credit spread blow-out
    aaa = dfetch.get_series("india_aaa")[0]
    gsec = dfetch.get_series("india_10y")[0]
    spread = (aaa - gsec).dropna()
    if len(spread) and float(spread.iloc[-1]) > 1.2:
        alerts.append(_sys_alert(
            f"India AAA credit spread wide ({float(spread.iloc[-1]):.2f}%)",
            "Financial", 2,
            "Widening spreads indicate deteriorating risk appetite / funding stress.",
        ))
    return alerts


def _sys_alert(title: str, category: str, severity: int, why: str) -> dict:
    return {
        "title": title, "summary": why, "category": category,
        "severity": severity, "severity_label": config.SEVERITY_LABELS[severity],
        "source": "Market Monitor", "url": "", "why": why,
        "impact": _IMPACT[category],
    }


# --------------------------------------------------------------------------- #
#  Aggregate
# --------------------------------------------------------------------------- #
def evaluate() -> dict:
    headlines = news_engine.fetch_headlines()
    news_alerts = [a for a in (_score_headline(h) for h in headlines) if a]
    market_alerts = _market_stress_alerts()
    alerts = market_alerts + news_alerts
    alerts.sort(key=lambda a: a["severity"], reverse=True)

    if alerts:
        max_sev = max(a["severity"] for a in alerts)
        n_high = sum(1 for a in alerts if a["severity"] >= 3)
        # Aggregate level: driven by the worst alert, escalated by breadth.
        level_idx = max_sev
        if max_sev == 3 and n_high >= 3:
            level_idx = 4
        global_level = config.SEVERITY_LABELS[level_idx]
    else:
        global_level = "Low"

    counts = {c: 0 for c in ("Geopolitical", "Financial", "Economic", "Market")}
    for a in alerts:
        counts[a["category"]] += 1

    return {
        "global_risk_level": global_level,
        "alerts": alerts[:25],
        "category_counts": counts,
        "n_alerts": len(alerts),
    }
