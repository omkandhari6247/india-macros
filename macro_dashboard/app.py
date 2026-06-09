"""
app.py
======
India Macro Intelligence Dashboard — Streamlit entry point.

Run:  streamlit run app.py

Layout (tabs):
  CIO Dashboard | Business Cycle | Consumer Demand | Inflation & Policy |
  United States | Global Risk | Portfolio | Diagnostics

The heavy lifting lives in the engine modules; this file is presentation +
caching + auto-refresh + the weekly PDF download button.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import alert_engine as ae
import business_cycle_engine as bce
import config
import data_fetcher as dfetch
import macro_scoring_engine as mse
import report_generator as rg

st.set_page_config(page_title="India Macro Intelligence",
                   page_icon="🇮🇳", layout="wide",
                   initial_sidebar_state="expanded")

# --------------------------------------------------------------------------- #
#  Styling
# --------------------------------------------------------------------------- #
st.markdown("""
<style>
    .main { background:#0e1117; }
    .metric-card{background:#161b26;border:1px solid #2a3142;border-radius:12px;
        padding:14px 16px;margin-bottom:8px;}
    .big{font-size:30px;font-weight:700;}
    .lbl{color:#8b94a7;font-size:12px;text-transform:uppercase;letter-spacing:.5px;}
    .pill{padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600;}
</style>
""", unsafe_allow_html=True)

GREEN, YELLOW, ORANGE, RED = "#2ecc71", "#f1c40f", "#e67e22", "#e74c3c"
RISK_COLOR = {"Low": GREEN, "Medium": YELLOW, "High": ORANGE, "Critical": RED}
TILT_COLOR = {"Overweight": GREEN, "Neutral": YELLOW, "Underweight": RED}


# --------------------------------------------------------------------------- #
#  Cached engine runs (TTL = refresh cadence)
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=config.CACHE_TTL_SECONDS, show_spinner=False)
def load_everything():
    cycle = bce.evaluate()
    demand = mse.consumer_demand_score()
    infl_in = mse.inflation_dashboard("india")
    infl_us = mse.inflation_dashboard("us")
    rbi = mse.rbi_rate_probability()
    fed = mse.fed_rate_probability()
    sens = mse.india_sensitivity(fed["bias"])
    risk = ae.evaluate()
    portfolio = mse.portfolio_regime(cycle, demand, infl_in, rbi,
                                     risk["global_risk_level"])
    return dict(cycle=cycle, demand=demand, infl_in=infl_in, infl_us=infl_us,
                rbi=rbi, fed=fed, sens=sens, risk=risk, portfolio=portfolio)


@st.cache_data(ttl=config.CACHE_TTL_SECONDS, show_spinner=False)
def series(key: str) -> pd.Series:
    return dfetch.get_series(key)[0]


# --------------------------------------------------------------------------- #
#  Reusable chart helpers
# --------------------------------------------------------------------------- #
def gauge(value: float, title: str, vmin=0, vmax=100,
          bands=((50, RED), (70, YELLOW), (100, GREEN))) -> go.Figure:
    steps, prev = [], vmin
    for upper, col in bands:
        steps.append(dict(range=[prev, upper], color=col))
        prev = upper
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value, title={"text": title, "font": {"size": 14}},
        gauge={"axis": {"range": [vmin, vmax]}, "bar": {"color": "#1d6fb8"},
               "steps": steps, "bgcolor": "#161b26"}))
    fig.update_layout(height=230, margin=dict(l=20, r=20, t=40, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", font_color="#e6e9ef")
    return fig


def line(keys, title, target=None, band=None):
    fig = go.Figure()
    for k in (keys if isinstance(keys, list) else [keys]):
        s = series(k).dropna().iloc[-120:]
        fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines",
                                 name=config.SERIES_BY_KEY[k].label))
    if target is not None:
        fig.add_hline(y=target, line_dash="dash", line_color=GREEN,
                      annotation_text=f"Target {target}")
    if band is not None:
        fig.add_hrect(y0=band[0], y1=band[1], fillcolor=GREEN, opacity=0.08,
                      line_width=0)
    fig.update_layout(title=title, height=300, paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="#161b26", font_color="#e6e9ef",
                      margin=dict(l=10, r=10, t=40, b=10),
                      legend=dict(orientation="h", y=-0.2))
    return fig


def prob_bar(d: dict, keys, title):
    fig = go.Figure(go.Bar(x=keys, y=[d[k] for k in keys],
                           marker_color=[GREEN, YELLOW, RED][:len(keys)],
                           text=[f"{d[k]}%" for k in keys], textposition="auto"))
    fig.update_layout(title=title, height=260, paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="#161b26", font_color="#e6e9ef",
                      margin=dict(l=10, r=10, t=40, b=10), yaxis_range=[0, 100])
    return fig


def traffic_light(level: str):
    order = ["Low", "Medium", "High", "Critical"]
    cols = [GREEN, YELLOW, ORANGE, RED]
    dots = "".join(
        f'<span style="display:inline-block;width:22px;height:22px;border-radius:50%;'
        f'margin:2px;background:{c if order[i]==level else "#2a3142"};'
        f'box-shadow:{f"0 0 12px {c}" if order[i]==level else "none"}"></span>'
        for i, c in enumerate(cols))
    st.markdown(dots, unsafe_allow_html=True)


def card(label, value, color="#e6e9ef"):
    st.markdown(
        f'<div class="metric-card"><div class="lbl">{label}</div>'
        f'<div class="big" style="color:{color}">{value}</div></div>',
        unsafe_allow_html=True)


def heatmap_pillars(pillars: dict, title: str):
    keys = list(pillars.keys())
    vals = [pillars[k] for k in keys]
    fig = go.Figure(go.Heatmap(
        z=[vals], x=keys, y=[""], colorscale=[[0, RED], [0.5, YELLOW], [1, GREEN]],
        zmin=0, zmax=100, text=[[f"{v:.0f}" for v in vals]],
        texttemplate="%{text}", showscale=False))
    fig.update_layout(title=title, height=140, paper_bgcolor="rgba(0,0,0,0)",
                      font_color="#e6e9ef", margin=dict(l=10, r=10, t=40, b=10))
    return fig


# --------------------------------------------------------------------------- #
#  Sidebar
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.title("🇮🇳 Macro Intelligence")
    st.caption("Institutional macro monitor — India focus")
    auto = st.toggle("Auto-refresh (15 min)", value=False)
    if st.button("🔄 Refresh now"):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    fred_ok = "✅" if config.FRED_API_KEY else "⚠️ synthetic"
    news_ok = "✅" if config.NEWS_API_KEY else "⚠️ RSS/sample"
    st.markdown(f"**FRED data:** {fred_ok}")
    st.markdown(f"**News feed:** {news_ok}")
    st.caption("Add keys in `.env` to switch from fallback to live data. "
               "Drop CSVs in `data/overrides/<key>.csv` for India series.")

D = load_everything()

# --------------------------------------------------------------------------- #
#  Tabs
# --------------------------------------------------------------------------- #
tabs = st.tabs(["📊 CIO Dashboard", "🔄 Business Cycle", "🛒 Consumer Demand",
                "📈 Inflation & Policy", "🇺🇸 United States", "🚨 Global Risk",
                "💼 Portfolio", "🩺 Diagnostics"])

# ---- CIO Dashboard -------------------------------------------------------- #
with tabs[0]:
    st.subheader("Executive CIO Dashboard")
    c = st.columns(7)
    with c[0]: card("Business Cycle", D["cycle"]["phase"])
    with c[1]:
        col = GREEN if D["demand"]["band"] == "Green" else YELLOW if D["demand"]["band"] == "Yellow" else RED
        card("Consumer Demand", f'{D["demand"]["score"]:.0f}', col)
    with c[2]:
        cpi = D["infl_in"]["CPI YoY"]["latest"]
        col = RED if cpi > config.RBI_UPPER_BAND else GREEN if cpi <= config.RBI_TARGET else YELLOW
        card("India CPI", f"{cpi:.1f}%", col)
    with c[3]: card("RBI Bias", D["rbi"]["bias"])
    with c[4]: card("Fed Bias", D["fed"]["bias"])
    with c[5]:
        lvl = D["risk"]["global_risk_level"]
        card("Global Risk", lvl, RISK_COLOR[lvl])
    with c[6]: card("Regime", D["portfolio"]["regime"])

    st.divider()
    g = st.columns(3)
    with g[0]:
        st.plotly_chart(gauge(D["cycle"]["composite_score"],
                              "Cycle Expansion Score"), use_container_width=True)
    with g[1]:
        st.plotly_chart(gauge(D["demand"]["score"], "Consumer Demand"),
                        use_container_width=True)
    with g[2]:
        st.markdown("**Global Risk Level**")
        traffic_light(D["risk"]["global_risk_level"])
        st.metric("Active alerts", D["risk"]["n_alerts"])
        st.caption(f"{D['cycle']['summary']}")

    st.divider()
    st.markdown("#### 📄 Weekly Investment Committee Report")
    pdf = rg.build_report(D["cycle"], D["demand"], D["infl_in"], D["infl_us"],
                          D["rbi"], D["fed"], D["sens"], D["risk"], D["portfolio"])
    st.download_button("⬇️ Download Weekly Macro PDF", data=pdf,
                       file_name=f"macro_committee_{pd.Timestamp.now():%Y%m%d}.pdf",
                       mime="application/pdf")

# ---- Business Cycle ------------------------------------------------------- #
with tabs[1]:
    st.subheader(f"Business Cycle — {D['cycle']['summary']}")
    cc = st.columns([1, 1.3])
    with cc[0]:
        st.plotly_chart(gauge(D["cycle"]["composite_score"], "Composite Score"),
                        use_container_width=True)
    with cc[1]:
        st.plotly_chart(heatmap_pillars(D["cycle"]["pillars"], "Pillar Scores"),
                        use_container_width=True)
    cd = D["cycle"]["detail"]
    m = st.columns(4)
    m[0].metric("10Y-2Y Spread", f"{cd['curve']['spread_10_2']:+.2f}%", cd['curve']['shape'])
    m[1].metric("AAA Spread", f"{cd['credit']['aaa_spread']:.2f}%", cd['credit']['appetite'])
    m[2].metric("Mfg PMI", f"{cd['pmi']['pmi']:.1f}", cd['pmi']['regime'])
    m[3].metric("Credit Growth", f"{cd['credit_growth']['credit_growth']:.1f}%",
                cd['credit_growth']['direction'])
    st.plotly_chart(line(["india_10y", "india_2y", "india_1y"],
                         "India G-Sec Yields"), use_container_width=True)
    st.plotly_chart(line(["india_aaa", "india_aa", "india_10y"],
                         "Corporate vs Government Yields"), use_container_width=True)

# ---- Consumer Demand ------------------------------------------------------ #
with tabs[2]:
    band = D["demand"]["band"]
    col = GREEN if band == "Green" else YELLOW if band == "Yellow" else RED
    st.subheader("Consumer Demand Dashboard")
    cc = st.columns([1, 1.4])
    with cc[0]:
        st.plotly_chart(gauge(D["demand"]["score"], f"Demand Score ({band})"),
                        use_container_width=True)
        st.caption(D["demand"]["interpretation"])
    with cc[1]:
        st.plotly_chart(heatmap_pillars(D["demand"]["components"],
                                        "Component Scores"), use_container_width=True)
    st.plotly_chart(line("india_gst", "GST Collections (₹ cr)"),
                    use_container_width=True)
    cc2 = st.columns(2)
    with cc2[0]:
        st.plotly_chart(line(["india_upi_value"], "UPI Value"), use_container_width=True)
        st.plotly_chart(line(["india_2w_sales"], "2-Wheeler Sales (rural demand)"),
                        use_container_width=True)
    with cc2[1]:
        st.plotly_chart(line(["india_pmi_mfg"], "Manufacturing PMI", target=50),
                        use_container_width=True)
        st.plotly_chart(line(["india_diesel", "india_petrol"], "Fuel Consumption"),
                        use_container_width=True)

# ---- Inflation & Policy --------------------------------------------------- #
with tabs[3]:
    st.subheader("Inflation & RBI Policy")
    cpi = D["infl_in"]["CPI YoY"]
    m = st.columns(4)
    m[0].metric("CPI YoY", f"{cpi['latest']:.1f}%", f"{cpi['distance_from_target']:+.1f}% vs target")
    m[1].metric("Core CPI", f"{D['infl_in']['Core CPI YoY']['latest']:.1f}%")
    m[2].metric("Food CPI", f"{D['infl_in']['Food CPI YoY']['latest']:.1f}%")
    m[3].metric("WPI YoY", f"{D['infl_in']['WPI YoY']['latest']:.1f}%")
    st.plotly_chart(line(["india_cpi", "india_core_cpi", "india_food_cpi"],
                         "India Inflation vs RBI Target", target=config.RBI_TARGET,
                         band=(config.RBI_LOWER_BAND, config.RBI_UPPER_BAND)),
                    use_container_width=True)
    st.divider()
    st.markdown("### RBI Rate Probability Engine")
    cc = st.columns([1, 1.3])
    with cc[0]:
        st.plotly_chart(prob_bar(D["rbi"], ["Cut", "Hold", "Hike"],
                                 f"Next Meeting — bias: {D['rbi']['bias']}"),
                        use_container_width=True)
        st.metric("Real policy rate", f"{D['rbi']['real_rate']:.1f}%")
    with cc[1]:
        st.markdown("**Reasoning**")
        for r in D["rbi"]["reasoning"]:
            st.markdown(f"- {r}")

# ---- United States -------------------------------------------------------- #
with tabs[4]:
    st.subheader("United States Monitor")
    m = st.columns(4)
    m[0].metric("US CPI", f"{D['infl_us']['US CPI YoY']['latest']:.1f}%")
    m[1].metric("Core CPI", f"{D['infl_us']['US Core CPI YoY']['latest']:.1f}%")
    m[2].metric("Unemployment", f"{dfetch.latest(series('us_unemployment')):.1f}%")
    m[3].metric("Fed Funds", f"{D['fed']['fed_funds']:.2f}%")
    st.plotly_chart(line(["us_cpi", "us_core_cpi"], "US Inflation"),
                    use_container_width=True)
    cc = st.columns(2)
    with cc[0]:
        st.plotly_chart(line(["us_unemployment"], "Unemployment"), use_container_width=True)
        st.plotly_chart(line(["us_10y", "us_2y"], "Treasury Yields"), use_container_width=True)
    with cc[1]:
        st.plotly_chart(prob_bar(D["fed"], ["Cut", "Hold", "Hike"],
                                 f"FedWatch nowcast — {D['fed']['implied_path']}"),
                        use_container_width=True)
        st.markdown("**Fed reasoning**")
        for r in D["fed"]["reasoning"]:
            st.markdown(f"- {r}")
    st.divider()
    st.markdown(f"### India Sensitivity — {D['sens']['scenario']}")
    sc = st.columns(4)
    for i, k in enumerate(["INR", "FII Flows", "Bonds", "Equities"]):
        sc[i].markdown(f"**{k}**  \n{D['sens'][k]}")

# ---- Global Risk ---------------------------------------------------------- #
with tabs[5]:
    lvl = D["risk"]["global_risk_level"]
    st.subheader("Global Risk Alert System")
    cc = st.columns([1, 2])
    with cc[0]:
        st.markdown(f"### Level: <span style='color:{RISK_COLOR[lvl]}'>{lvl}</span>",
                    unsafe_allow_html=True)
        traffic_light(lvl)
        for k, v in D["risk"]["category_counts"].items():
            st.metric(k, v)
    with cc[1]:
        for a in D["risk"]["alerts"]:
            c = config.SEVERITY_COLORS[a["severity"]]
            with st.expander(f"[{a['severity_label']}] {a['title']}  ·  {a['category']}"):
                st.markdown(f"<span class='pill' style='background:{c};color:#000'>"
                            f"{a['severity_label']} Risk</span>", unsafe_allow_html=True)
                st.write(a["summary"])
                st.caption(f"Why it matters: {a['why']}  · Source: {a['source']}")
                imp = a["impact"]
                st.markdown("**Potential impact** — " + " | ".join(
                    f"**{k}:** {imp[k]}" for k in
                    ("India", "Equities", "Bonds", "INR", "Commodities")))
                if a["url"]:
                    st.markdown(f"[Read more]({a['url']})")

# ---- Portfolio ------------------------------------------------------------ #
with tabs[6]:
    p = D["portfolio"]
    st.subheader(f"Portfolio Positioning — Regime: {p['regime']}")
    st.caption(p["rationale"])
    items = list(p["tilts"].items())
    cols = st.columns(4)
    for i, (asset, tilt) in enumerate(items):
        with cols[i % 4]:
            st.markdown(
                f"<div class='metric-card'><div class='lbl'>{asset}</div>"
                f"<div style='font-size:18px;font-weight:700;color:{TILT_COLOR[tilt]}'>"
                f"{tilt}</div></div>", unsafe_allow_html=True)

# ---- Diagnostics ---------------------------------------------------------- #
with tabs[7]:
    st.subheader("Data Source Diagnostics")
    st.caption("Which series are live vs. running on synthetic/override fallback. "
               "Configure FRED_API_KEY and drop override CSVs to go fully live.")
    st.dataframe(dfetch.data_health(), use_container_width=True, height=600)

# --------------------------------------------------------------------------- #
#  Auto-refresh
# --------------------------------------------------------------------------- #
if auto:
    time.sleep(config.REFRESH_SECONDS)
    st.cache_data.clear()
    st.rerun()
