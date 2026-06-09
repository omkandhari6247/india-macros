"""
report_generator.py
===================
Generates the downloadable "Weekly Macro Investment Committee Report" (PDF)
summarising every section and flagging week-over-week changes pulled from the
SQLite snapshot store.

Pure reportlab — no Streamlit dependency, so it can also be run on a schedule
(e.g. cron / a Friday batch job) independent of the dashboard.
"""

from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

import config
import data_fetcher as dfetch

_NAVY = colors.HexColor("#0b2545")
_ACCENT = colors.HexColor("#1d6fb8")
_TILT_COLORS = {"Overweight": colors.HexColor("#2ecc71"),
                "Neutral": colors.HexColor("#f1c40f"),
                "Underweight": colors.HexColor("#e74c3c")}


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("H0", parent=ss["Title"], textColor=_NAVY,
                          fontSize=20, spaceAfter=4))
    ss.add(ParagraphStyle("Sub", parent=ss["Normal"], textColor=colors.grey,
                          fontSize=9, spaceAfter=12))
    ss.add(ParagraphStyle("H1b", parent=ss["Heading2"], textColor=_ACCENT,
                          fontSize=13, spaceBefore=12, spaceAfter=6))
    ss.add(ParagraphStyle("Body", parent=ss["Normal"], fontSize=9.5,
                          leading=13, spaceAfter=4))
    return ss


def _delta_str(metric: str, current: float, fmt: str = "{:.1f}") -> str:
    prev = dfetch.previous_snapshot(metric, days_ago=7)
    if prev is None:
        return fmt.format(current) + "  (no prior week)"
    chg = current - prev
    arrow = "▲" if chg > 0 else "▼" if chg < 0 else "■"
    return f"{fmt.format(current)}  ({arrow} {chg:+.1f} WoW)"


def build_report(cycle: dict, demand: dict, infl_in: dict, infl_us: dict,
                 rbi: dict, fed: dict, sens: dict, risk: dict,
                 portfolio: dict) -> bytes:
    """Assemble the weekly PDF and return it as raw bytes."""
    # Persist this run so next week's WoW deltas have a reference.
    dfetch.snapshot({
        "cycle_score": cycle["composite_score"],
        "demand_score": demand["score"],
        "india_cpi": infl_in["CPI YoY"]["latest"],
        "rbi_cut_prob": rbi["Cut"],
        "fed_cut_prob": fed["Cut"],
    })

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=1.5 * cm,
                            bottomMargin=1.5 * cm, leftMargin=1.6 * cm,
                            rightMargin=1.6 * cm,
                            title="Weekly Macro Investment Committee Report")
    ss = _styles()
    flow = []

    flow.append(Paragraph("Weekly Macro Investment Committee Report", ss["H0"]))
    flow.append(Paragraph(
        f"India Macro Intelligence • Generated {datetime.now():%d %b %Y, %H:%M}",
        ss["Sub"]))

    # --- Executive snapshot table ----------------------------------------- #
    flow.append(Paragraph("1 · Executive Snapshot", ss["H1b"]))
    snap = [
        ["Indicator", "Reading"],
        ["Business Cycle", cycle["summary"]],
        ["Cycle Score", _delta_str("cycle_score", cycle["composite_score"])],
        ["Consumer Demand", f"{demand['score']:.0f}/100 ({demand['band']})"],
        ["India CPI", _delta_str("india_cpi", infl_in["CPI YoY"]["latest"]) + " %"],
        ["RBI Bias", f"{rbi['bias']}  (Cut {rbi['Cut']}% / Hold {rbi['Hold']}% / Hike {rbi['Hike']}%)"],
        ["Fed Bias", f"{fed['bias']}  (Cut {fed['Cut']}% / Hold {fed['Hold']}% / Hike {fed['Hike']}%)"],
        ["Global Risk Level", risk["global_risk_level"]],
        ["Portfolio Regime", portfolio["regime"]],
    ]
    t = Table(snap, colWidths=[5 * cm, 12 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6fa")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    flow += [t, Spacer(1, 8)]

    # --- Business cycle ---------------------------------------------------- #
    flow.append(Paragraph("2 · Business Cycle", ss["H1b"]))
    flow.append(Paragraph(
        f"<b>{cycle['summary']}</b> — {cycle.get('cfa_reasoning','')} Composite "
        f"expansion score {cycle['composite_score']:.0f}/100. Pillar scores — " +
        ", ".join(f"{k}: {v:.0f}" for k, v in cycle["pillars"].items()) + ".",
        ss["Body"]))
    cd = cycle["detail"]
    flow.append(Paragraph(
        f"Yield curve is <b>{cd['curve']['shape']}</b> (10Y-2Y "
        f"{cd['curve']['spread_10_2']:+.2f}%). Credit: {cd['credit']['appetite']} "
        f"(AAA spread {cd['credit']['aaa_spread']:.2f}%). PMI "
        f"{cd['pmi']['pmi']:.1f} ({cd['pmi']['regime']}).", ss["Body"]))

    # --- Inflation & policy ------------------------------------------------ #
    flow.append(Paragraph("3 · Inflation & Central Banks", ss["H1b"]))
    flow.append(Paragraph(
        f"India CPI {infl_in['CPI YoY']['latest']:.1f}% "
        f"({infl_in['CPI YoY']['direction']}), "
        f"{infl_in['CPI YoY']['distance_from_target']:+.1f}% vs the 4% target. "
        f"RBI nowcast bias: <b>{rbi['bias']}</b> (real rate ~{rbi['real_rate']:.1f}%). "
        f"US core CPI {fed['core_cpi']:.1f}%; Fed bias <b>{fed['bias']}</b> "
        f"({fed['implied_path']}).", ss["Body"]))
    flow.append(Paragraph("RBI reasoning: " + " ".join(rbi["reasoning"]), ss["Body"]))

    # --- Fed -> India ------------------------------------------------------ #
    flow.append(Paragraph("4 · Fed → India Transmission", ss["H1b"]))
    flow.append(Paragraph(
        f"<b>{sens['scenario']}</b> — INR: {sens['INR']} FII: {sens['FII Flows']} "
        f"Bonds: {sens['Bonds']} Equities: {sens['Equities']}", ss["Body"]))

    # --- Risk -------------------------------------------------------------- #
    flow.append(Paragraph("5 · Global Risk", ss["H1b"]))
    flow.append(Paragraph(
        f"Aggregate level: <b>{risk['global_risk_level']}</b> "
        f"({risk['n_alerts']} active alerts — " +
        ", ".join(f"{k}: {v}" for k, v in risk["category_counts"].items()) + ").",
        ss["Body"]))
    for a in risk["alerts"][:5]:
        flow.append(Paragraph(
            f"• [{a['severity_label']}] {a['title']} — {a['summary'][:160]}",
            ss["Body"]))

    # --- Positioning ------------------------------------------------------- #
    flow.append(Paragraph("6 · Portfolio Positioning", ss["H1b"]))
    flow.append(Paragraph(portfolio["rationale"], ss["Body"]))
    tilt_items = list(portfolio["tilts"].items())
    rows = [["Asset", "Tilt", "Asset", "Tilt"]]
    for i in range(0, len(tilt_items), 2):
        left = tilt_items[i]
        right = tilt_items[i + 1] if i + 1 < len(tilt_items) else ("", "")
        rows.append([left[0], left[1], right[0], right[1]])
    tt = Table(rows, colWidths=[4.2 * cm, 4.2 * cm, 4.2 * cm, 4.2 * cm])
    style = [("BACKGROUND", (0, 0), (-1, 0), _NAVY),
             ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
             ("FONTSIZE", (0, 0), (-1, -1), 8.5),
             ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey)]
    for r, row in enumerate(rows[1:], start=1):
        for c, tilt in ((1, row[1]), (3, row[3])):
            if tilt in _TILT_COLORS:
                style.append(("TEXTCOLOR", (c, r), (c, r), _TILT_COLORS[tilt]))
                style.append(("FONTNAME", (c, r), (c, r), "Helvetica-Bold"))
    tt.setStyle(TableStyle(style))
    flow += [tt, Spacer(1, 10)]

    flow.append(Paragraph(
        "<i>Methodology: rule-based nowcasts combining yield-curve, credit, "
        "activity and inflation signals. Probabilities are model estimates, "
        "not market-priced. For internal investment-committee use; not "
        "investment advice.</i>",
        ParagraphStyle("disc", parent=ss["Body"], fontSize=7.5,
                       textColor=colors.grey)))

    doc.build(flow)
    return buf.getvalue()
