"""
insight_engine.py
=================
The "analyst voice" layer. Turns raw scores into explanation + context that an
investment committee can actually read, framed around the CFA Level III
business-cycle / capital-market-expectations and term-structure frameworks.

Nothing here fetches data — it consumes the dicts the engines already produce
and returns human-readable strings / structures. Two kinds of content:

  * STATIC reference (how a score is built, what an indicator means for
    equities) — the `*_NOTES` dicts and `PHASE_PLAYBOOK`.
  * DYNAMIC narrative (what the *current* reading implies) — the `*_narrative`
    functions, which branch on the live values.

All framework descriptions are written in plain language; they paraphrase the
standard business-cycle/term-structure framework rather than reproducing any
curriculum text.
"""

from __future__ import annotations

import config


# --------------------------------------------------------------------------- #
#  How each composite score is constructed (methodology transparency)
# --------------------------------------------------------------------------- #
SCORING_NOTES = {
    "business_cycle": (
        "**Business-cycle score (0-100 = expansion strength).** A weighted blend: "
        "yield curve 40%, credit spreads 30%, PMI trend 15%, credit growth 15%. "
        "Each pillar is mapped to 0-100 from its *level* and its *momentum*. "
        "Crucially, the **phase** is not read off the score alone — it is "
        "cross-checked against the yield-curve shape and inflation direction "
        "(CFA framework), so a high score with a *steep* curve and *low* "
        "inflation reads as mid-expansion, not late expansion."
    ),
    "consumer_demand": (
        "**Consumer-demand score (0-100).** GST 20%, UPI 20%, PMI 15%, auto 15%, "
        "petroleum 15%, retail credit 15%. Each component is scored from its YoY "
        "growth and trend direction. >70 green (broad-based demand), 50-70 yellow "
        "(mixed), <50 red (contracting). It is a coincident-to-leading read on "
        "the household/discretionary side — relevant for consumer, auto, "
        "financials and retail-exposed equities."
    ),
    "rbi": (
        "**RBI rate nowcast.** A transparent rule-based tilt starting from "
        "neutral, then nudged by: CPI vs the 2-6% band, inflation direction, the "
        "real policy rate (repo − CPI), PMI level and credit-growth trend. These "
        "are *model* probabilities, not OIS/market-implied odds — swap in "
        "overnight-index-swap data for true market pricing."
    ),
    "fed": (
        "**Fed nowcast.** Same rule-based approach driven by US core CPI, headline "
        "trend and unemployment direction (the Fed's dual mandate). Model "
        "estimate, not fed-funds-futures pricing."
    ),
    "global_risk": (
        "**Global risk level.** Two inputs: (1) keyword scoring of macro headlines "
        "into Geopolitical/Financial/Economic/Market with severity 1-4, and "
        "(2) quantitative stress triggers (curve inversion, VIX spike, credit "
        "blow-out). The aggregate is the worst single alert, escalated when "
        "several high-severity items cluster."
    ),
    "portfolio": (
        "**Portfolio regime.** Growth direction × inflation direction → one of "
        "Goldilocks / Reflation / Late-Cycle Boom / Stagflation / Deflationary "
        "Slowdown / Recovery. Each maps to a tilt template (Over/Neutral/Under) "
        "that is then de-risked one notch if global risk is High/Critical."
    ),
}


# --------------------------------------------------------------------------- #
#  What each macro indicator means for equity markets (CFA-framed)
# --------------------------------------------------------------------------- #
INDICATOR_NOTES = {
    "yield_curve": (
        "Slope (10Y−2Y / 10Y−1Y) is the single best cycle barometer. **Steep/"
        "steepening** ≈ early cycle or expected easing → risk-on, favours "
        "cyclicals & banks (NIM steepens). **Flattening** ≈ tightening, maturing "
        "cycle → trim high-beta. **Inverted** ≈ market pricing cuts/slowdown — a "
        "historically reliable recession lead indicator → rotate to quality & "
        "duration."
    ),
    "credit_spreads": (
        "AAA/AA over G-Sec proxies risk appetite. **Tight & tightening** = "
        "confident credit, supports equity multiples and leveraged/cyclical "
        "names. **Widening** = stress, repricing of risk — equities (esp. "
        "financials, mid/small-cap) typically de-rate first."
    ),
    "pmi": (
        "Manufacturing PMI is a leading activity gauge. >50 = expansion, <50 = "
        "contraction; the *direction* matters as much as the level. Rising PMI "
        "supports industrials, materials and cyclical earnings revisions."
    ),
    "credit_growth": (
        "Bank credit growth shows the transmission of policy into the real "
        "economy. Accelerating credit underpins banks/NBFCs and capex-linked "
        "sectors; decelerating credit is an early warning for financials."
    ),
    "cpi": (
        "Inflation vs the RBI's 4% target (2-6% band) drives policy and real "
        "yields. Above-band, rising CPI → tightening risk, pressures rate-"
        "sensitives (real estate, autos, banks' valuations) and long-duration "
        "growth equities; rewards pricing-power and real-asset plays."
    ),
    "gst": (
        "GST collections are a near-real-time, broad tax base proxy for nominal "
        "activity and formalisation — a clean coincident demand signal."
    ),
    "upi": (
        "UPI value/volume tracks the velocity of discretionary spending; "
        "decelerating momentum often precedes softer consumer-facing earnings."
    ),
    "auto": (
        "2-wheeler sales proxy rural demand; entry cars proxy mass-market urban "
        "demand. Both are classic early-cyclical consumption reads."
    ),
    "petroleum": (
        "Diesel = freight/industrial activity; petrol = mobility; ATF = "
        "discretionary travel. A grounded read on physical economic throughput."
    ),
    "vix": (
        "Implied volatility = the market's fear gauge. Sustained spikes coincide "
        "with de-risking, multiple compression and a flight from high-beta to "
        "defensives."
    ),
}


# --------------------------------------------------------------------------- #
#  CFA-style phase playbook: description + asset & equity-sector implications
# --------------------------------------------------------------------------- #
PHASE_PLAYBOOK = {
    "Recovery": {
        "desc": "Economy emerging from the trough; policy still accommodative, "
                "short rates low, output gap wide. Yield curve typically at its "
                "steepest; confidence turning up.",
        "equities": "Strong rebound phase — high-beta cyclicals, small-caps, "
                    "banks and consumer discretionary lead. India: financials, "
                    "autos, real estate, capital goods.",
        "bonds": "Yields near cycle lows; long end may begin to rise. Credit "
                 "spreads wide but tightening — credit risk starts to pay.",
        "tilt": "Overweight equities & cyclicals; underweight cash & defensives.",
    },
    "Early Expansion": {
        "desc": "Growth accelerating, output gap closing, short rates beginning "
                "to firm. Curve still upward-sloping but flattening starts; "
                "inflation contained.",
        "equities": "Broad cyclical leadership continues — industrials, "
                    "financials, consumer discretionary, tech.",
        "bonds": "Yields rising; credit still tight. Duration a headwind.",
        "tilt": "Overweight equities/cyclicals; neutral duration.",
    },
    "Mid Expansion": {
        "desc": "Solid, broad-based growth near potential; policy drifting to "
                "neutral; curve flatter; inflation beginning to nudge up. The "
                "'sweet spot' but with maturing risk.",
        "equities": "Positive but more moderate returns and broader "
                    "participation — quality, tech, leaders. Reduce the most "
                    "aggressive cyclical bets.",
        "bonds": "Range-bound to higher yields; carry-driven.",
        "tilt": "Overweight equities (selective), neutral bonds.",
    },
    "Late Expansion": {
        "desc": "Economy at/above capacity, positive output gap, inflation "
                "rising and the central bank tightening. Curve flat-to-inverting; "
                "credit spreads complacently tight. Volatility builds.",
        "equities": "Late melt-ups possible but risk/reward deteriorates. "
                    "Inflation beneficiaries lead — energy, materials, real "
                    "assets — then begin rotating to quality & defensives.",
        "bonds": "Unattractive until rates peak; inflation erodes real returns.",
        "tilt": "Neutral equities, raise gold/real assets, start adding quality.",
    },
    "Peak": {
        "desc": "Activity plateauing at a high level; rates at cyclical highs; "
                "curve flat/inverted; leading indicators rolling over.",
        "equities": "Topping process — defensives (staples, healthcare, "
                    "utilities) and low-beta lead; trim cyclicals.",
        "bonds": "Lengthen duration — yields near their peak, set to fall.",
        "tilt": "Underweight cyclicals, overweight defensives & duration.",
    },
    "Slowdown": {
        "desc": "Growth decelerating; policy still tight but turning; curve "
                "inverted then bull-steepening as cuts are priced; credit "
                "spreads widening.",
        "equities": "Defensive leadership — staples, pharma, utilities, quality, "
                    "low-vol. India IT can outperform on weak-INR earnings if US "
                    "demand holds. Avoid leverage/high-beta.",
        "bonds": "Duration rallies as the easing cycle approaches; favour govvies "
                 "over credit.",
        "tilt": "Underweight equities/cyclicals; overweight bonds, gold, cash.",
    },
    "Recession": {
        "desc": "Output contracting; aggressive easing; curve steepening; credit "
                "spreads wide. A trough-formation phase.",
        "equities": "Defensives until the inflection, then early-cyclicals as the "
                    "market discounts recovery 6-9 months ahead of data.",
        "bonds": "Long-duration government bonds outperform early; credit "
                 "attractive once spreads peak.",
        "tilt": "Max defensive → pivot to early-cyclical at signs of inflection.",
    },
}


# --------------------------------------------------------------------------- #
#  Dynamic narratives
# --------------------------------------------------------------------------- #
def business_cycle_narrative(cycle: dict) -> str:
    """One-paragraph CFA-framed read of the current cycle classification."""
    phase = cycle["phase"]
    pb = PHASE_PLAYBOOK.get(phase, {})
    cd = cycle["detail"]
    curve = cd["curve"]
    return (
        f"**{cycle['summary']}.** {pb.get('desc','')}\n\n"
        f"Right now the India curve is **{curve['shape'].lower()}** "
        f"(10Y−2Y {curve['spread_10_2']:+.2f}%), credit appetite is "
        f"*{cd['credit']['appetite'].lower()}*, and PMI is {cd['pmi']['pmi']:.1f} "
        f"({cd['pmi']['regime'].lower()}). Per the CFA term-structure read, a "
        f"{curve['shape'].lower()} curve is consistent with this phase. "
        f"**Equity implication:** {pb.get('equities','')}"
    )


def equity_context(regime: str, cycle: dict, risk_level: str, infl: dict) -> str:
    """Tie the regime + cycle + risk into an equity-positioning paragraph."""
    pb = PHASE_PLAYBOOK.get(cycle["phase"], {})
    cpi = infl.get("CPI YoY", {})
    infl_note = ""
    if cpi.get("latest", 0) > config.RBI_TARGET and cpi.get("direction") == "Rising":
        infl_note = (" Inflation is above target and rising, which argues for "
                     "pricing-power names and real assets over long-duration "
                     "growth and rate-sensitives.")
    risk_note = ""
    if risk_level in ("High", "Critical"):
        risk_note = (f" Global risk is **{risk_level}** — the model de-risks "
                     "growth-cyclical tilts one notch and lifts gold/cash as a "
                     "hedge.")
    return (f"Regime: **{regime}** ({cycle['phase']}). {pb.get('equities','')}"
            f"{infl_note}{risk_note}")


def data_status_note(is_live_fred: bool, is_live_news: bool) -> tuple[str, str]:
    """Returns (level, message) where level ∈ {'demo','partial','live'}."""
    if not is_live_fred:
        return ("demo",
                "⚠️ **DEMO DATA** — no FRED key / India CSVs detected, so every "
                "series is seeded *synthetic* data. Classifications (incl. the "
                "business-cycle phase) are illustrative only. Add a FRED key and "
                "India override CSVs to make this a live read.")
    if is_live_fred and not is_live_news:
        return ("partial",
                "🟡 **PARTIAL LIVE** — FRED series are live; India-specific "
                "series (GST/UPI/auto/PMI) still need override CSVs, and news is "
                "on RSS/sample. Treat India-specific scores as indicative.")
    return ("live", "🟢 **LIVE** — FRED + news feeds active.")
