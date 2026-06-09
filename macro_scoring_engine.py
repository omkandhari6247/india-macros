"""
macro_scoring_engine.py
=======================
Sections 2, 3, 4 and 6.

* consumer_demand_score()     — Section 2 composite (0-100, colour-banded)
* inflation_dashboard()       — Section 3 India inflation pack vs RBI target
* rbi_rate_probability()      — Section 3 rule-based cut/hold/hike odds
* fed_rate_probability()      — Section 4 Fed odds + market-implied path proxy
* india_sensitivity()         — Section 4 Fed→India transmission commentary
* portfolio_regime()          — Section 6 regime label + asset tilts

These are deliberately transparent, rule-based models (not black boxes) so an
investment committee can audit every input and weight. Probabilities are
heuristic nowcasts, NOT market-priced — clearly labelled as such in the UI.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config
import data_fetcher as dfetch


# --------------------------------------------------------------------------- #
#  Section 2 — Consumer Demand
# --------------------------------------------------------------------------- #
def _momentum_score(key: str, lo_yoy: float = -5, hi_yoy: float = 20) -> tuple[float, dict]:
    """Generic 0-100 sub-score from a series' YoY growth, with trend pack."""
    s = dfetch.get_series(key)[0]
    st = dfetch.trend_stats(s)
    yoy = st.get("yoy", np.nan)
    base = 50.0 if np.isnan(yoy) else np.clip((yoy - lo_yoy) / (hi_yoy - lo_yoy) * 100, 0, 100)
    if st.get("direction") == "Rising":
        base = min(100, base + 5)
    elif st.get("direction") == "Falling":
        base = max(0, base - 5)
    return float(base), st


def consumer_demand_score() -> dict:
    gst, gst_st = _momentum_score("india_gst")
    upi_v, upi_st = _momentum_score("india_upi_value", hi_yoy=40)
    pmi = dfetch.get_series("india_pmi_mfg")[0]
    pmi_cur = dfetch.latest(pmi)
    pmi_score = float(np.clip((pmi_cur - 45) / 13 * 100, 0, 100))

    # Auto = average of 2W (rural) and entry car (mass market)
    tw, tw_st = _momentum_score("india_2w_sales", hi_yoy=15)
    ec, ec_st = _momentum_score("india_entry_car", hi_yoy=15)
    auto = (tw + ec) / 2

    # Petroleum = diesel+petrol+ATF
    pet = np.mean([_momentum_score(k, hi_yoy=12)[0]
                   for k in ("india_diesel", "india_petrol", "india_atf")])

    rc, rc_st = _momentum_score("india_retail_credit", lo_yoy=5, hi_yoy=22)

    w = config.CONSUMER_DEMAND_WEIGHTS
    composite = (gst * w["gst"] + upi_v * w["upi"] + pmi_score * w["pmi"] +
                 auto * w["auto"] + pet * w["petroleum"] + rc * w["retail_credit"])

    band = ("Green" if composite > config.DEMAND_GREEN
            else "Yellow" if composite >= config.DEMAND_YELLOW else "Red")

    return {
        "score": round(composite, 1),
        "band": band,
        "components": {
            "GST": round(gst, 1), "UPI": round(upi_v, 1),
            "PMI": round(pmi_score, 1), "Auto": round(auto, 1),
            "Petroleum": round(pet, 1), "Retail Credit": round(rc, 1),
        },
        "trends": {
            "GST Collections": gst_st, "UPI Value": upi_st,
            "2W Sales": tw_st, "Entry Car": ec_st, "Retail Credit": rc_st,
            "Mfg PMI": dfetch.trend_stats(pmi),
        },
        "interpretation": ("Expanding demand" if composite >= config.DEMAND_YELLOW
                           else "Contracting demand"),
    }


# --------------------------------------------------------------------------- #
#  Section 3 — Inflation
# --------------------------------------------------------------------------- #
def inflation_dashboard(prefix: str = "india") -> dict:
    keys = {
        "india": ["india_cpi", "india_wpi", "india_core_cpi", "india_food_cpi"],
        "us": ["us_cpi", "us_core_cpi", "us_ppi"],
    }[prefix]
    out = {}
    for k in keys:
        s = dfetch.get_series(k)[0]
        st = dfetch.trend_stats(s)
        st["distance_from_target"] = (st["latest"] - config.RBI_TARGET
                                      if prefix == "india" else None)
        out[config.SERIES_BY_KEY[k].label] = st
    return out


# --------------------------------------------------------------------------- #
#  Section 3 — RBI rate probability (rule-based nowcast)
# --------------------------------------------------------------------------- #
def rbi_rate_probability() -> dict:
    cpi = dfetch.trend_stats(dfetch.get_series("india_cpi")[0])
    repo = dfetch.latest(dfetch.get_series("india_repo")[0])
    growth = dfetch.trend_stats(dfetch.get_series("india_pmi_mfg")[0])
    cg = dfetch.trend_stats(dfetch.get_series("india_credit_growth")[0])

    cpi_now = cpi["latest"]
    real_rate = repo - cpi_now

    # Start neutral, then nudge with explainable factors.
    cut, hold, hike = 33.0, 34.0, 33.0
    reasons = []

    if cpi_now < config.RBI_TARGET:
        cut += 18; hike -= 12
        reasons.append(f"CPI {cpi_now:.1f}% is below the 4% target — disinflation supports easing.")
    elif cpi_now > config.RBI_UPPER_BAND:
        hike += 22; cut -= 18
        reasons.append(f"CPI {cpi_now:.1f}% breaches the 6% upper band — bias to tighten.")
    else:
        hold += 8
        reasons.append(f"CPI {cpi_now:.1f}% is within the 2-6% band — argues for patience.")

    if cpi["direction"] == "Falling":
        cut += 8; reasons.append("Inflation trend is falling.")
    elif cpi["direction"] == "Rising":
        hike += 8; reasons.append("Inflation trend is rising.")

    if real_rate > 1.5:
        cut += 10; reasons.append(f"Real policy rate ~{real_rate:.1f}% is restrictive, leaving room to cut.")
    elif real_rate < 0:
        hike += 8; reasons.append(f"Real policy rate ~{real_rate:.1f}% is negative — tightening pressure.")

    if growth["latest"] < 50:
        cut += 8; reasons.append("Mfg PMI below 50 signals weakening growth.")
    if cg["direction"] == "Falling":
        cut += 5; reasons.append("Slowing credit growth argues for support.")

    probs = np.clip(np.array([cut, hold, hike]), 1, None)
    probs = probs / probs.sum() * 100
    return {
        "Cut": round(float(probs[0])), "Hold": round(float(probs[1])),
        "Hike": round(float(probs[2])),
        "real_rate": round(real_rate, 2), "repo": repo, "cpi": cpi_now,
        "reasoning": reasons,
        "bias": ["Cut", "Hold", "Hike"][int(np.argmax(probs))],
    }


# --------------------------------------------------------------------------- #
#  Section 4 — Fed probability + India sensitivity
# --------------------------------------------------------------------------- #
def fed_rate_probability() -> dict:
    cpi = dfetch.trend_stats(dfetch.get_series("us_cpi")[0])
    core = dfetch.trend_stats(dfetch.get_series("us_core_cpi")[0])
    unemp = dfetch.trend_stats(dfetch.get_series("us_unemployment")[0])
    ffr = dfetch.latest(dfetch.get_series("us_fedfunds")[0])

    cut, hold, hike = 33.0, 34.0, 33.0
    reasons = []
    if core["latest"] < 3.0:
        cut += 18; reasons.append(f"Core CPI {core['latest']:.1f}% nearing target supports cuts.")
    elif core["latest"] > 4.0:
        hike += 18; reasons.append(f"Core CPI {core['latest']:.1f}% is sticky — restrictive bias.")
    else:
        hold += 8; reasons.append(f"Core CPI {core['latest']:.1f}% argues for a pause.")

    if unemp["direction"] == "Rising":
        cut += 14; reasons.append("Rising unemployment shifts the Fed toward its employment mandate.")
    if cpi["direction"] == "Falling":
        cut += 6; reasons.append("Headline inflation is decelerating.")

    probs = np.clip(np.array([cut, hold, hike]), 1, None)
    probs = probs / probs.sum() * 100
    bias = ["Cut", "Hold", "Hike"][int(np.argmax(probs))]
    return {
        "Cut": round(float(probs[0])), "Hold": round(float(probs[1])),
        "Hike": round(float(probs[2])),
        "fed_funds": ffr, "core_cpi": core["latest"],
        "reasoning": reasons, "bias": bias,
        "implied_path": ("Easing" if bias == "Cut" else
                         "Tightening" if bias == "Hike" else "On hold"),
    }


def india_sensitivity(fed_bias: str) -> dict:
    """Directional Fed→India transmission commentary."""
    if fed_bias == "Cut":
        return {
            "scenario": "Fed Cutting",
            "INR": "Supportive — narrower rate differential eases INR pressure; mild appreciation bias.",
            "FII Flows": "Positive — lower US yields push capital toward EM/India risk assets.",
            "Bonds": "Bullish — global yield compression pulls Indian G-Sec yields lower.",
            "Equities": "Bullish — cheaper global liquidity supports valuations, esp. rate-sensitives.",
        }
    if fed_bias == "Hike":
        return {
            "scenario": "Fed Hiking",
            "INR": "Pressured — wider differential and stronger USD weigh on INR.",
            "FII Flows": "Negative — higher US yields pull capital out of EM.",
            "Bonds": "Bearish — imported tightening lifts domestic yields.",
            "Equities": "Headwind — risk-off and valuation compression, esp. high-multiple names.",
        }
    return {
        "scenario": "Fed On Hold",
        "INR": "Range-bound — differential stable; driven by domestic flows and oil.",
        "FII Flows": "Neutral — flows hinge on relative growth and earnings.",
        "Bonds": "Stable — domestic inflation and RBI dominate.",
        "Equities": "Neutral — earnings and domestic cycle in the driver's seat.",
    }


# --------------------------------------------------------------------------- #
#  Section 6 — Portfolio regime & tilts
# --------------------------------------------------------------------------- #
def portfolio_regime(cycle: dict, demand: dict, infl: dict,
                     rbi: dict, global_risk_level: str) -> dict:
    """
    Map the macro mosaic to a regime label and a full asset-tilt table.
    Regime grid: growth direction × inflation direction.
    """
    cpi = infl.get("CPI YoY", {})
    infl_rising = cpi.get("direction") == "Rising"
    infl_high = cpi.get("latest", 4) > config.RBI_UPPER_BAND
    growth_strong = demand["score"] >= config.DEMAND_YELLOW and \
        cycle["phase"] in ("Recovery", "Early Expansion", "Mid Expansion")
    late_cycle = cycle["phase"] in ("Late Expansion", "Peak")
    contracting = cycle["phase"] in ("Slowdown", "Recession")

    if contracting and infl_high:
        regime = "Stagflation"
    elif contracting and not infl_high:
        regime = "Deflationary Slowdown"
    elif growth_strong and infl_rising:
        regime = "Reflation"
    elif growth_strong and not infl_rising:
        regime = "Goldilocks"
    elif late_cycle:
        regime = "Late Cycle Boom"
    else:
        regime = "Recovery"

    # Base tilt templates per regime. O/N/U = Overweight/Neutral/Underweight.
    grid = {
        "Goldilocks": dict(Equities="Overweight", Bonds="Neutral", Gold="Underweight",
                           USD="Underweight", Cash="Underweight", Cyclicals="Overweight",
                           Defensives="Underweight", Banks="Overweight", IT="Overweight",
                           Industrials="Overweight", Consumer="Overweight",
                           RealEstate="Overweight"),
        "Reflation": dict(Equities="Overweight", Bonds="Underweight", Gold="Neutral",
                          USD="Neutral", Cash="Underweight", Cyclicals="Overweight",
                          Defensives="Underweight", Banks="Overweight", IT="Neutral",
                          Industrials="Overweight", Consumer="Neutral",
                          RealEstate="Overweight"),
        "Late Cycle Boom": dict(Equities="Neutral", Bonds="Neutral", Gold="Overweight",
                                USD="Neutral", Cash="Neutral", Cyclicals="Neutral",
                                Defensives="Overweight", Banks="Neutral", IT="Overweight",
                                Industrials="Neutral", Consumer="Neutral",
                                RealEstate="Underweight"),
        "Stagflation": dict(Equities="Underweight", Bonds="Underweight", Gold="Overweight",
                            USD="Overweight", Cash="Overweight", Cyclicals="Underweight",
                            Defensives="Overweight", Banks="Underweight", IT="Neutral",
                            Industrials="Underweight", Consumer="Underweight",
                            RealEstate="Underweight"),
        "Deflationary Slowdown": dict(Equities="Underweight", Bonds="Overweight",
                                      Gold="Neutral", USD="Overweight", Cash="Overweight",
                                      Cyclicals="Underweight", Defensives="Overweight",
                                      Banks="Underweight", IT="Neutral", Industrials="Underweight",
                                      Consumer="Neutral", RealEstate="Underweight"),
        "Recovery": dict(Equities="Overweight", Bonds="Neutral", Gold="Neutral",
                         USD="Underweight", Cash="Neutral", Cyclicals="Overweight",
                         Defensives="Neutral", Banks="Overweight", IT="Neutral",
                         Industrials="Overweight", Consumer="Overweight",
                         RealEstate="Overweight"),
    }
    tilts = grid[regime].copy()

    # Overlay: high/critical global risk => de-risk one notch on growth assets.
    if global_risk_level in ("High", "Critical"):
        for k in ("Equities", "Cyclicals", "Banks", "RealEstate"):
            if tilts.get(k) == "Overweight":
                tilts[k] = "Neutral"
            elif tilts.get(k) == "Neutral":
                tilts[k] = "Underweight"
        tilts["Gold"] = "Overweight"
        tilts["Cash"] = "Overweight"

    rationale = (f"Regime '{regime}' derived from cycle phase "
                 f"'{cycle['phase']}', demand score {demand['score']:.0f}, "
                 f"inflation {cpi.get('latest', float('nan')):.1f}% "
                 f"({cpi.get('direction', 'n/a')}), RBI bias '{rbi['bias']}', "
                 f"global risk '{global_risk_level}'.")
    return {"regime": regime, "tilts": tilts, "rationale": rationale}
