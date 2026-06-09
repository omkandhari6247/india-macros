"""
business_cycle_engine.py
========================
Section 1 — India Business Cycle Monitor.

Determines the current business-cycle phase from four pillars, combined with
the weights defined in config.BUSINESS_CYCLE_WEIGHTS:

    Yield Curve    40%   (10Y-2Y, 10Y-1Y spreads; shape & momentum)
    Credit Spreads 30%   (AAA & AA over G-Sec; level & momentum)
    PMI Trend      15%   (level vs 50 and direction)
    Credit Growth  15%   (bank credit YoY level and direction)

Output: a phase from the 7-phase taxonomy plus a confidence score. The mapping
from a continuous "cycle momentum" score to a discrete phase uses both the
score *level* and its *direction*, which is what distinguishes, e.g.,
'Late Expansion' (high level, slowing) from 'Mid Expansion' (high level,
still rising).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config
import data_fetcher as dfetch

PHASES = ["Recession", "Recovery", "Early Expansion", "Mid Expansion",
          "Late Expansion", "Peak", "Slowdown"]


# --------------------------------------------------------------------------- #
#  Pillar sub-scores (each returns a 0-100 "expansion strength" + commentary)
# --------------------------------------------------------------------------- #
def _curve_score() -> tuple[float, dict]:
    y10 = dfetch.get_series("india_10y")[0]
    y2 = dfetch.get_series("india_2y")[0]
    y1 = dfetch.get_series("india_1y")[0]

    spread_10_2 = (y10 - y2).dropna()
    spread_10_1 = (y10 - y1).dropna()
    s2 = float(spread_10_2.iloc[-1])
    s1 = float(spread_10_1.iloc[-1])
    # 6-period change in the 10-2 spread => steepening (+) / flattening (-)
    momentum = float(spread_10_2.iloc[-1] - spread_10_2.iloc[-7]) \
        if len(spread_10_2) > 7 else 0.0

    # Map spread level (-1%..+2%) and steepening into 0-100.
    level_score = np.clip((s2 + 1.0) / 3.0 * 100, 0, 100)
    momentum_score = np.clip(50 + momentum * 100, 0, 100)
    score = 0.7 * level_score + 0.3 * momentum_score

    if s2 < 0:
        shape = "Inverted"
    elif momentum > 0.05:
        shape = "Steepening"
    elif momentum < -0.05:
        shape = "Flattening"
    else:
        shape = "Stable"
    return float(score), {"spread_10_2": s2, "spread_10_1": s1,
                          "shape": shape, "momentum": momentum}


def _credit_score() -> tuple[float, dict]:
    gsec = dfetch.get_series("india_10y")[0]
    aaa = dfetch.get_series("india_aaa")[0]
    aa = dfetch.get_series("india_aa")[0]

    aaa_spread = (aaa - gsec).dropna()
    aa_spread = (aa - gsec).dropna()
    sa = float(aaa_spread.iloc[-1])
    sb = float(aa_spread.iloc[-1])
    widening = float(aaa_spread.iloc[-1] - aaa_spread.iloc[-7]) \
        if len(aaa_spread) > 7 else 0.0

    # Tight spreads => risk appetite => expansion. Map 0.3%..1.5% AAA spread.
    level_score = np.clip((1.5 - sa) / 1.2 * 100, 0, 100)
    momentum_score = np.clip(50 - widening * 200, 0, 100)
    score = 0.7 * level_score + 0.3 * momentum_score

    if widening > 0.05:
        appetite = "Risk appetite falling / credit stress"
    elif widening < -0.05:
        appetite = "Risk appetite rising"
    else:
        appetite = "Stable"
    return float(score), {"aaa_spread": sa, "aa_spread": sb,
                          "appetite": appetite, "widening": widening}


def _pmi_score() -> tuple[float, dict]:
    pmi = dfetch.get_series("india_pmi_mfg")[0]
    st = dfetch.trend_stats(pmi)
    cur = st["latest"]
    # 45..58 mapped to 0..100, blended with direction.
    level_score = np.clip((cur - 45) / 13 * 100, 0, 100)
    dir_bonus = 10 if st["direction"] == "Rising" else -10 if st["direction"] == "Falling" else 0
    score = np.clip(level_score + dir_bonus, 0, 100)
    return float(score), {"pmi": cur, "direction": st["direction"],
                          "regime": "Expansion" if cur > 50 else "Contraction"}


def _credit_growth_score() -> tuple[float, dict]:
    cg = dfetch.get_series("india_credit_growth")[0]
    st = dfetch.trend_stats(cg)
    cur = st["latest"]
    # 5%..20% YoY mapped to 0..100.
    level_score = np.clip((cur - 5) / 15 * 100, 0, 100)
    dir_bonus = 8 if st["direction"] == "Rising" else -8 if st["direction"] == "Falling" else 0
    score = np.clip(level_score + dir_bonus, 0, 100)
    return float(score), {"credit_growth": cur, "direction": st["direction"]}


# --------------------------------------------------------------------------- #
#  Phase classification
# --------------------------------------------------------------------------- #
def _classify(score: float, momentum: float, curve_shape: str,
              infl_rising: bool, infl_high: bool) -> tuple[str, float, str]:
    """
    Map a composite expansion score to a phase using the CFA business-cycle /
    term-structure framework — NOT the score alone.

    The score sets the broad activity zone; the YIELD CURVE shape and the
    INFLATION trend then disambiguate *where in the expansion* we are. This is
    the key fix: 'late expansion' in the CFA sense requires the overheating
    signature (flattening/inverting curve and/or rising, elevated inflation),
    so a high score with a STEEP curve and contained inflation correctly reads
    as mid-expansion, not late.
    """
    rising = momentum >= 0
    flattening = curve_shape in ("Flattening", "Inverted")
    inverted = curve_shape == "Inverted"
    overheating = flattening or (infl_rising and infl_high)
    reason = ""

    if score < 25:
        phase = "Recession"
        reason = "Activity score deeply contractionary."
    elif score < 40:
        if inverted and not rising:
            phase = "Recession"
            reason = "Weak activity with an inverted curve — contraction signal."
        else:
            phase = "Recovery" if rising else "Slowdown"
            reason = ("Low-but-improving activity; steepening curve typical of "
                      "early recovery." if rising else
                      "Weak, decelerating activity — slowdown.")
    elif score < 60:
        if not rising or inverted:
            phase = "Slowdown"
            reason = "Moderating activity / flat-inverted curve — maturing into slowdown."
        else:
            phase = "Early Expansion"
            reason = "Improving activity with a still-upward curve — early expansion."
    elif score < 78:
        # Strong activity: curve + inflation decide mid vs late.
        if overheating and rising:
            phase = "Late Expansion"
            reason = ("Strong activity AND overheating signature (flattening "
                      "curve / rising-elevated inflation) — late expansion.")
        elif not rising or inverted:
            phase = "Slowdown"
            reason = "Strong level but rolling over with a flattening curve."
        else:
            phase = "Mid Expansion"
            reason = ("Strong activity but curve still upward and inflation "
                      "contained — mid expansion, not yet late.")
    else:  # very strong activity
        if not rising or inverted:
            phase = "Peak"
            reason = "Activity at cyclical highs and rolling over — peak."
        elif overheating:
            phase = "Late Expansion"
            reason = "Above-trend activity with overheating signs — late expansion."
        else:
            phase = "Mid Expansion"
            reason = ("Above-trend activity but no overheating signature yet — "
                      "still mid expansion.")

    boundaries = [25, 40, 60, 78]
    dist = min(abs(score - b) for b in boundaries)
    confidence = float(np.clip(52 + dist * 2.0, 50, 95))
    return phase, confidence, reason


def evaluate() -> dict:
    """Run the full Section 1 engine. Returns scores, phase and detail dicts."""
    curve, curve_d = _curve_score()
    credit, credit_d = _credit_score()
    pmi, pmi_d = _pmi_score()
    cg, cg_d = _credit_growth_score()

    w = config.BUSINESS_CYCLE_WEIGHTS
    composite = (curve * w["yield_curve"] + credit * w["credit_spreads"] +
                 pmi * w["pmi_trend"] + cg * w["credit_growth"])

    # Momentum = curve + pmi direction proxy (forward-looking pillars).
    momentum = curve_d["momentum"] * 50 + (pmi_d["pmi"] - 50)

    # CFA cross-checks: pull inflation trend to disambiguate the phase.
    cpi = dfetch.trend_stats(dfetch.get_series("india_cpi")[0])
    infl_rising = cpi.get("direction") == "Rising"
    infl_high = cpi.get("latest", 4.0) > config.RBI_TARGET

    phase, confidence, reason = _classify(
        composite, momentum, curve_d["shape"], infl_rising, infl_high)

    return {
        "phase": phase,
        "confidence": round(confidence, 1),
        "composite_score": round(composite, 1),
        "cfa_reasoning": reason,
        "cpi": round(cpi.get("latest", float("nan")), 2),
        "cpi_direction": cpi.get("direction", "n/a"),
        "pillars": {
            "Yield Curve": round(curve, 1),
            "Credit Spreads": round(credit, 1),
            "PMI Trend": round(pmi, 1),
            "Credit Growth": round(cg, 1),
        },
        "detail": {"curve": curve_d, "credit": credit_d,
                   "pmi": pmi_d, "credit_growth": cg_d},
        "summary": f"{phase} ({confidence:.0f}% confidence)",
    }
