"""
streamlit_app.py — Replenishment Assistant

Report section 12: how a business would actually consume this project.

Four screens:
    Overview        — the catalogue at a glance
    Product Lookup  — the buyer's daily tool
    Basket Explorer — which products must be stocked together
    Action List     — what to do on Monday morning

Run:  streamlit run app/streamlit_app.py
"""

from pathlib import Path
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"

st.set_page_config(page_title="Replenishment Assistant", page_icon="📦",
                   layout="wide", initial_sidebar_state="expanded")

# ────────────────────────────────────────────────────────────── palette
# Matches .streamlit/config.toml. Change both together, or the CSS and the
# Streamlit chrome will disagree.
BG        = "#0F1620"
SURFACE   = "#182231"
BORDER    = "#25334A"
TEXT      = "#E5EAF2"
MUTED     = "#94A3B8"
GRID      = "#1F2C3E"

TEAL   = "#2DD4BF"
GREEN  = "#34D399"
AMBER  = "#FBBF24"
RED    = "#F87171"
NAVY   = "#60A5FA"
GREY   = "#64748B"

st.markdown(f"""
<style>
    .block-container {{padding-top: 3.5rem; padding-bottom: 4rem; max-width: 1400px;}}
    .hero + .sub {{margin-bottom: .5rem;}}

    /* metric cards */
    div[data-testid="stMetric"] {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 12px;
        padding: 16px 20px;
    }}
    div[data-testid="stMetric"]:hover {{border-color: {TEAL}55;}}
    div[data-testid="stMetricLabel"] p {{
        font-size: .72rem; color: {MUTED}; font-weight: 600;
        text-transform: uppercase; letter-spacing: .06em;
    }}
    div[data-testid="stMetricValue"] {{font-size: 1.9rem; font-weight: 700; color: {TEXT};}}
    div[data-testid="stMetricDelta"] {{font-size: .8rem;}}

    /* class badges */
    .badge {{display:inline-block; padding:7px 18px; border-radius:24px;
             font-weight:700; font-size:.92rem; letter-spacing:.02em;
             border:1px solid transparent;}}
    .b-green {{background:{GREEN}1F; color:{GREEN}; border-color:{GREEN}55;}}
    .b-amber {{background:{AMBER}1F; color:{AMBER}; border-color:{AMBER}55;}}
    .b-red   {{background:{RED}1F;   color:{RED};   border-color:{RED}55;}}
    .b-grey  {{background:{GREY}2A;  color:{MUTED}; border-color:{GREY}55;}}

    /* headings */
    .hero {{font-size:2.5rem; font-weight:800; line-height:1.12; margin:0;
            color:{TEXT}; letter-spacing:-.02em;}}
    .sub  {{color:{MUTED}; font-size:1rem; margin:.35rem 0 0 0;}}

    /* callout */
    .note {{background:{SURFACE}; border-left:3px solid {TEAL};
            padding:14px 18px; border-radius:0 8px 8px 0;
            font-size:.9rem; color:{MUTED}; line-height:1.6;}}
    .note b {{color:{TEXT};}}

    /* tabs */
    button[data-baseweb="tab"] {{font-weight:600; letter-spacing:.01em;}}
    div[data-baseweb="tab-highlight"] {{background-color:{TEAL};}}

    /* sidebar */
    section[data-testid="stSidebar"] {{border-right:1px solid {BORDER};}}
    section[data-testid="stSidebar"] .block-container {{padding-top:1.5rem;}}

    /* tables + expanders */
    div[data-testid="stDataFrame"] {{border:1px solid {BORDER}; border-radius:10px;}}
    hr {{border-color:{BORDER};}}
</style>
""", unsafe_allow_html=True)


def style_fig(fig, height=340, legend_title=None):
    """One place to keep every chart consistent with the theme."""
    fig.update_layout(
        height=height,
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT, size=12),
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=BORDER,
                        font=dict(color=TEXT, size=12)),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=MUTED),
                    title=dict(text=legend_title or "", font=dict(color=MUTED))),
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=BORDER,
                     title_font=dict(color=MUTED), tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=BORDER,
                     title_font=dict(color=MUTED), tickfont=dict(color=MUTED))
    return fig


# ────────────────────────────────────────────────────────────── data
@st.cache_data(show_spinner="Loading analysis…")
def load():
    sku = pd.read_csv(PROC / "sku_profile.csv")
    policy = pd.read_csv(PROC / "inventory_policy.csv")
    rules = pd.read_csv(PROC / "association_rules.csv")
    weekly = pd.read_csv(PROC / "sku_weekly.csv", parse_dates=["week"])
    fc = pd.read_csv(PROC / "forecast_accuracy.csv")
    pt = PROC / "pullthrough_test.csv"
    pt = pd.read_csv(pt) if pt.exists() else pd.DataFrame()
    sku["product"] = sku["product"].fillna(sku["StockCode"])
    return sku, policy, rules, weekly, fc, pt


sku, policy, rules, weekly, fc, pull = load()
WEEKS = weekly["week"].nunique()
ALL_WEEKS = pd.date_range(weekly.week.min(), weekly.week.max(), freq="W-MON")

POLICY = {
    "AX": ("b-green", "Tight reorder point, low safety stock",
           "High revenue, predictable demand. Forecasting works here — the cheapest class "
           "to protect and the most expensive to get wrong."),
    "AY": ("b-amber", "Moderate safety stock, review monthly",
           "High revenue but variable. Worth active management."),
    "AZ": ("b-amber", "Expensive to protect — buy agility, not stock",
           "High revenue, erratic demand. Safety stock big enough to cover the spikes ties "
           "up serious capital; a shorter lead time is usually cheaper."),
    "BX": ("b-green", "Automate, review quarterly", "Predictable and mid-value."),
    "BY": ("b-grey", "Standard policy", "Middle of the catalogue on both axes."),
    "BZ": ("b-amber", "Consider make-to-order", "Erratic and mid-value — poor stock candidate."),
    "CX": ("b-green", "Automate entirely, minimal review",
           "Low value but predictable. Cheap to hold, needs no attention."),
    "CY": ("b-grey", "Low priority", "Little revenue, some variability."),
    "CZ": ("b-red", "DELIST CANDIDATE",
           "Lowest revenue, most erratic demand — the worst capital-to-value ratio in the "
           "catalogue. Stock to order, or drop the line."),
}


def badge(cls):
    style, head, _ = POLICY.get(cls, ("b-grey", cls, ""))
    return f'<span class="badge {style}">{cls} — {head}</span>'


def series_for(code):
    w = weekly[weekly.StockCode == code].set_index("week")["units"]
    return w.reindex(ALL_WEEKS, fill_value=0)


# ────────────────────────────────────────────────────────────── sidebar
with st.sidebar:
    st.markdown("## 📦 Replenishment\n### Assistant")
    st.caption("Retail Sales Analysis for Inventory Management")
    st.divider()
    page = st.radio("Go to", ["📊 Overview", "🔍 Product Lookup",
                              "🔗 Basket Explorer", "⚠️ Action List"],
                    label_visibility="collapsed")
    st.divider()
    st.markdown("##### Catalogue")
    st.markdown(
        f"**{len(sku):,}** SKUs &nbsp;·&nbsp; **£{sku.revenue.sum()/1e6:.1f}M** revenue  \n"
        f"**{(sku.ABC=='A').sum():,}** class A = 80% of revenue  \n"
        f"**{(sku['class']=='CZ').sum():,}** delist candidates  \n"
        f"**{WEEKS}** weeks of history"
    )

# ══════════════════════════════════════════════════════════════ OVERVIEW
if page == "📊 Overview":
    st.markdown('<p class="hero">The catalogue at a glance</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub">Where the revenue is, and where the capital is stuck.</p>',
                unsafe_allow_html=True)
    st.write("")

    a, b, c, d = st.columns(4)
    a.metric("Total revenue", f"£{sku.revenue.sum()/1e6:.2f}M")
    b.metric("Class A SKUs", f"{(sku.ABC=='A').sum():,}",
             f"{100*(sku.ABC=='A').mean():.0f}% of catalogue", delta_color="off")
    c.metric("Delist candidates", f"{(sku['class']=='CZ').sum():,}",
             f"{100*(sku['class']=='CZ').mean():.0f}% of catalogue", delta_color="off")
    if len(pull):
        d.metric("Lost when a partner stocks out",
                 f"{100*(1-pull.ratio.median()):.1f}%", "median across pairs",
                 delta_color="off")

    st.write("")
    left, right = st.columns([3, 2])

    with left:
        st.markdown("##### Revenue concentration")
        s = sku.sort_values("revenue", ascending=False).reset_index(drop=True)
        s["rank"] = np.arange(1, len(s) + 1)
        s["cum"] = 100 * s.revenue.cumsum() / s.revenue.sum()
        n80 = int((s.cum <= 80).sum() + 1)

        fig = go.Figure()
        fig.add_scatter(x=s["rank"], y=s["cum"], mode="lines",
                        line=dict(color=NAVY, width=3), name="cumulative %",
                        hovertemplate="rank %{x}<br>%{y:.1f}% of revenue<extra></extra>")
        fig.add_hline(y=80, line=dict(color=RED, dash="dash"))
        fig.add_vline(x=n80, line=dict(color=RED, dash="dash"))
        fig.add_annotation(x=n80, y=80, text=f"  {n80:,} SKUs → 80%",
                           showarrow=False, xanchor="left", font=dict(color=RED, size=13))
        fig.update_layout(xaxis_title="SKUs ranked by revenue",
                          yaxis_title="cumulative % of revenue", showlegend=False)
        style_fig(fig, 340); fig.update_yaxes(range=[0, 101])
        st.plotly_chart(fig, use_container_width=True)
        st.markdown(f'<div class="note"><b>{100*n80/len(s):.0f}% of the catalogue produces '
                    f'80% of the revenue.</b> Applying the same stock cover across a range '
                    f'this skewed guarantees both failures at once — capital stuck in the '
                    f'tail, thin cover on the items that pay.</div>', unsafe_allow_html=True)

    with right:
        st.markdown("##### The nine-cell policy grid")
        g = (sku.groupby(["ABC", "XYZ"]).agg(skus=("StockCode", "size"),
                                             revenue=("revenue", "sum")).reset_index())
        # rows reversed so A sits at the TOP, as a reader expects
        piv = g.pivot(index="ABC", columns="XYZ", values="skus").reindex(
            index=["C", "B", "A"], columns=["X", "Y", "Z"]).fillna(0)
        rev = g.pivot(index="ABC", columns="XYZ", values="revenue").reindex(
            index=["C", "B", "A"], columns=["X", "Y", "Z"]).fillna(0)
        txt = [[f"<b>{int(piv.values[i][j]):,}</b><br>£{rev.values[i][j]/1000:,.0f}k"
                for j in range(3)] for i in range(3)]

        fig = go.Figure(go.Heatmap(
            z=rev.values, x=["X<br>stable", "Y<br>variable", "Z<br>erratic"],
            y=["C<br>last 5%", "B<br>next 15%", "A<br>top 80%"],
            text=txt, texttemplate="%{text}", colorscale=[[0, SURFACE], [0.5, "#1D4ED8"], [1, TEAL]], showscale=False,
            hovertemplate="%{y} / %{x}<br>£%{z:,.0f} revenue<extra></extra>"))
        style_fig(fig, 340)
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('<div class="note"><b>Volume and volatility are near-independent.</b> '
                    'A high-revenue product is not automatically predictable — which is why '
                    'ABC alone is not enough to set a stocking policy.</div>',
                    unsafe_allow_html=True)

    st.write("")
    st.markdown("##### Where the revenue actually sits")
    top = sku.nlargest(15, "revenue").sort_values("revenue")
    fig = px.bar(top, x="revenue", y="product", orientation="h", color="ABC",
                 color_discrete_map={"A": GREEN, "B": AMBER, "C": RED},
                 hover_data={"class": True, "units": ":,", "revenue": ":,.0f"})
    fig.update_layout(yaxis_title="", xaxis_title="revenue (£)")
    style_fig(fig, 430, legend_title="class")
    st.plotly_chart(fig, use_container_width=True)

# ══════════════════════════════════════════════════════════ PRODUCT LOOKUP
elif page == "🔍 Product Lookup":
    st.markdown('<p class="hero">Product lookup</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub">What should I order, and what must not run out with it?</p>',
                unsafe_allow_html=True)

    f1, f2, f3 = st.columns([3, 1, 1])
    with f1:
        opts = sku.sort_values("revenue", ascending=False)["product"].tolist()
        choice = st.selectbox("Search for a product", opts, index=0)
    with f2:
        lead = st.select_slider("Lead time", [1, 2, 3, 4], value=2,
                                format_func=lambda x: f"{x} wk")
    with f3:
        service = st.select_slider("Service level", ["90%", "95%", "99%"], value="95%")

    row = sku[sku["product"] == choice].iloc[0]
    code = row.StockCode
    style, head, detail = POLICY.get(row["class"], ("b-grey", "—", ""))

    st.write("")
    st.markdown(badge(row["class"]), unsafe_allow_html=True)
    st.markdown(f'<div class="note" style="margin-top:10px">{detail}</div>',
                unsafe_allow_html=True)
    st.write("")

    m = st.columns(4)
    m[0].metric("Revenue", f"£{row.revenue:,.0f}")
    m[1].metric("Units sold", f"{row.units:,.0f}")
    m[2].metric("Weeks with sales", f"{row.weeks_active:.0f} / {WEEKS}")
    m[3].metric("Volatility (CV)", f"{row.cv:.2f}",
                "stable" if row.cv <= .75 else ("variable" if row.cv <= 1.5 else "erratic"),
                delta_color="off")

    t1, t2, t3 = st.tabs(["📐 Reorder point", "🔗 Never stock out alone", "📈 Demand history"])

    with t1:
        p = policy[policy.StockCode == code]
        if len(p) == 0:
            st.warning(
                f"**No reorder point — and that is the answer, not a gap.**\n\n"
                f"This product sells in only {row.weeks_active:.0f} of {WEEKS} weeks with a "
                f"CV of {row.cv:.2f}. Forecasting was run only for the {len(policy)} SKUs "
                f"with enough regular history to justify it.\n\n"
                f"For intermittent demand the right response is a **policy**, not a "
                f"forecast: {head.lower()}."
            )
        else:
            p = p.iloc[0]
            rop = p[f"ROP_{lead}w_{service}"]
            cycle = p.weekly_demand * lead
            safety = rop - cycle

            k = st.columns([2, 1, 1, 1])
            k[0].metric("REORDER AT", f"{rop:,.0f} units")
            k[1].metric("Cycle stock", f"{cycle:,.0f}")
            k[2].metric("Safety stock", f"{safety:,.0f}")
            k[3].metric("Weekly demand", f"{p.weekly_demand:,.1f}")

            st.markdown("##### How the recommendation moves with your assumptions")
            grid = pd.DataFrame(
                {sl: [policy.loc[policy.StockCode == code, f"ROP_{lt}w_{sl}"].iloc[0]
                      for lt in (1, 2, 3, 4)] for sl in ("90%", "95%", "99%")},
                index=[1, 2, 3, 4])
            fig = go.Figure()
            for sl, col in zip(("90%", "95%", "99%"), (GREEN, AMBER, RED)):
                fig.add_scatter(x=grid.index, y=grid[sl], mode="lines+markers", name=sl,
                                line=dict(color=col, width=3), marker=dict(size=9))
            fig.add_vline(x=lead, line=dict(color=NAVY, dash="dot"))
            fig.update_layout(xaxis_title="lead time (weeks)",
                              yaxis_title="reorder point (units)",
                              xaxis=dict(tickmode="array", tickvals=[1, 2, 3, 4]))
            style_fig(fig, 300, legend_title="service level")
            st.plotly_chart(fig, use_container_width=True)

            st.markdown('<div class="note">Lead time is not recorded in the source data, so '
                        'it is exposed as a control rather than hidden as an assumption. '
                        'Note that doubling it does not double the reorder point — safety '
                        'stock scales with the <b>square root</b> of lead time.</div>',
                        unsafe_allow_html=True)

            f = fc[fc.StockCode == code]
            if len(f):
                f = f.iloc[0]
                if f.beats_naive:
                    st.success(f"**The model earns its place.** Error {f.mae_hw:.1f} "
                               f"units/week against a naive forecast's {f.mae_naive:.1f} — "
                               f"{f.improvement:.0f}% better.")
                else:
                    st.warning(f"**The model does not beat doing nothing here** "
                               f"({f.mae_hw:.1f} vs {f.mae_naive:.1f} units/week). Assuming "
                               f"next week resembles this week is as good. Worth reporting, "
                               f"not hiding.")

    with t2:
        if len(pull):
            st.markdown(
                f'<div class="note">Measured across <b>{len(pull)} product pairs</b>: when a '
                f'product goes out of stock, the items normally bought with it lose a median '
                f'<b>{100*(1-pull.ratio.median()):.1f}%</b> of their sales. A stockout does '
                f'not cost one product\'s revenue — it costs part of the whole basket.</div>',
                unsafe_allow_html=True)
            st.write("")

        r = rules[rules.A == code].sort_values("lift", ascending=False)
        if len(r) == 0:
            st.info("No strong co-purchase partners at the thresholds used. This product is "
                    "bought largely on its own and can be stocked independently.")
        else:
            strong = r[r.lift >= 5]
            if len(strong):
                st.error(f"**{len(strong)} pair(s) above lift 5 — co-stocking rule applies.** "
                         f"These must not be allowed to run out independently of this product.")

            fig = px.bar(r.head(10).sort_values("lift"), x="lift", y="B_name",
                         orientation="h", color="lift", color_continuous_scale="Teal",
                         hover_data={"support": ":.3f", "confidence": ":.2f"})
            fig.add_vline(x=5, line=dict(color=RED, dash="dash"))
            fig.update_layout(yaxis_title="", xaxis_title="lift (1 = independent)",
                              coloraxis_showscale=False)
            style_fig(fig, 380)
            st.plotly_chart(fig, use_container_width=True)

            show = r[["B_name", "support", "confidence", "lift"]].copy()
            show.columns = ["Bought with", "Support", "Confidence", "Lift"]
            st.dataframe(show, use_container_width=True, hide_index=True,
                         column_config={
                             "Support": st.column_config.NumberColumn(format="%.3f"),
                             "Confidence": st.column_config.ProgressColumn(
                                 format="%.2f", min_value=0, max_value=1),
                             "Lift": st.column_config.NumberColumn(format="%.1f")})
            st.caption("Ranked by **lift**, never confidence. Confidence is inflated by "
                       "popularity — almost everything looks 'confidently' bought alongside "
                       "a best-seller. Lift controls for that.")

    with t3:
        s = series_for(code)
        fig = go.Figure()
        fig.add_scatter(x=s.index, y=s.values, mode="lines", fill="tozeroy",
                        line=dict(color=NAVY, width=2), name="units",
                        hovertemplate="%{x|%d %b %Y}<br>%{y:,} units<extra></extra>")
        fig.add_hline(y=s.mean(), line=dict(color=AMBER, dash="dash"),
                      annotation_text=f"mean {s.mean():.0f}")
        fig.update_layout(xaxis_title="", yaxis_title="units per week")
        style_fig(fig, 340)
        st.plotly_chart(fig, use_container_width=True)

        k = st.columns(4)
        k[0].metric("Mean / week", f"{s.mean():.1f}")
        k[1].metric("Peak week", f"{s.max():,.0f}")
        k[2].metric("Zero-sale weeks", f"{(s==0).sum()}")
        k[3].metric("Class", row.XYZ)

        st.markdown(f'<div class="note">Volatility is measured across all {WEEKS} weeks '
                    f'<b>including weeks with no sales</b>. A product that sells nothing for '
                    f'months <i>is</i> erratic — measuring only its active weeks would hide '
                    f'exactly the behaviour the XYZ axis exists to find.</div>',
                    unsafe_allow_html=True)

# ══════════════════════════════════════════════════════ BASKET EXPLORER
elif page == "🔗 Basket Explorer":
    st.markdown('<p class="hero">Basket explorer</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub">Which products are genuinely bought together — and which '
                'just happen to both be popular.</p>', unsafe_allow_html=True)
    st.write("")

    c1, c2 = st.columns([1, 3])
    with c1:
        min_lift = st.slider("Minimum lift", 1.0, float(rules.lift.max()), 2.0, 0.5)
        st.metric("Rules shown", f"{(rules.lift>=min_lift).sum():,}", f"of {len(rules):,}")
        st.metric("Co-stocking pairs", f"{(rules.lift>=5).sum():,}", "lift ≥ 5")

    r = rules[rules.lift >= min_lift]

    with c2:
        fig = px.scatter(r, x="support", y="confidence", size="lift", color="lift",
                         color_continuous_scale="Teal", size_max=26,
                         hover_name="A_name", hover_data={"B_name": True, "lift": ":.1f"})
        fig.update_layout(xaxis_title="support — how often the pair appears",
                          yaxis_title="confidence — how reliably B follows A")
        style_fig(fig, 400)
        st.plotly_chart(fig, use_container_width=True)

    st.markdown('<div class="note"><b>Low support, high confidence is the pattern to look '
                'for.</b> These pairs are not in many baskets — but when one is bought the '
                'other very often follows. That is exactly what a co-stocking rule is for, '
                'and it is why support alone would have thrown these away.</div>',
                unsafe_allow_html=True)
    st.write("")

    st.markdown("##### Strongest pairs")
    top = r.nlargest(15, "lift").sort_values("lift")
    fig = px.bar(top, x="lift", y=top.A_name.str[:26] + " → " + top.B_name.str[:26],
                 orientation="h", color="lift", color_continuous_scale="Teal")
    fig.update_layout(yaxis_title="", xaxis_title="lift", coloraxis_showscale=False)
    style_fig(fig, 460)
    st.plotly_chart(fig, use_container_width=True)

    show = r.nlargest(200, "lift")[["A_name", "B_name", "support", "confidence", "lift"]]
    show.columns = ["Product A", "Product B", "Support", "Confidence", "Lift"]
    st.dataframe(show, use_container_width=True, hide_index=True, height=320,
                 column_config={"Support": st.column_config.NumberColumn(format="%.3f"),
                                "Confidence": st.column_config.NumberColumn(format="%.2f"),
                                "Lift": st.column_config.NumberColumn(format="%.1f")})
    st.download_button("⬇ Download these rules as CSV",
                       show.to_csv(index=False).encode(), "association_rules.csv", "text/csv")

# ══════════════════════════════════════════════════════════ ACTION LIST
else:
    st.markdown('<p class="hero">Action list</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub">What to do on Monday morning.</p>', unsafe_allow_html=True)
    st.write("")

    t1, t2, t3 = st.tabs(["🗑 Delist candidates", "🔒 Co-stocking rules",
                          "🎯 Forecast not worth it"])

    with t1:
        cz = sku[sku["class"] == "CZ"].sort_values("revenue")
        a, b, c = st.columns(3)
        a.metric("Delist candidates", f"{len(cz):,}")
        b.metric("Share of catalogue", f"{100*len(cz)/len(sku):.0f}%")
        c.metric("Share of revenue", f"{100*cz.revenue.sum()/sku.revenue.sum():.1f}%")

        st.markdown(f'<div class="note"><b>{len(cz):,} SKUs — '
                    f'{100*len(cz)/len(sku):.0f}% of the catalogue — generate only '
                    f'{100*cz.revenue.sum()/sku.revenue.sum():.1f}% of revenue, with the most '
                    f'erratic demand in the range. Every one carries stock, warehouse space '
                    f'and working capital. Stock to order, or drop the line.</div>',
                    unsafe_allow_html=True)
        st.write("")
        show = cz[["StockCode", "product", "revenue", "units", "weeks_active", "cv"]].head(300)
        st.dataframe(show, use_container_width=True, hide_index=True, height=380,
                     column_config={
                         "revenue": st.column_config.NumberColumn("Revenue", format="£%.0f"),
                         "weeks_active": st.column_config.ProgressColumn(
                             "Weeks active", format="%d", min_value=0, max_value=WEEKS),
                         "cv": st.column_config.NumberColumn("Volatility", format="%.2f")})
        st.download_button("⬇ Download the full delist list",
                           cz.to_csv(index=False).encode(), "delist_candidates.csv", "text/csv")

    with t2:
        strong = rules[rules.lift >= 5].sort_values("lift", ascending=False)
        st.metric("Pairs that must not stock out independently", f"{len(strong):,}")
        st.markdown('<div class="note">For each pair below, the two reorder points should be '
                    'reviewed <b>together</b>. Letting one run out breaks the basket both '
                    'depend on — and the pull-through test measured that cost.</div>',
                    unsafe_allow_html=True)
        st.write("")
        show = strong[["A_name", "B_name", "lift", "confidence", "support"]]
        show.columns = ["If this runs out…", "…this suffers", "Lift", "Confidence", "Support"]
        st.dataframe(show, use_container_width=True, hide_index=True, height=420,
                     column_config={"Lift": st.column_config.NumberColumn(format="%.1f"),
                                    "Confidence": st.column_config.ProgressColumn(
                                        format="%.2f", min_value=0, max_value=1),
                                    "Support": st.column_config.NumberColumn(format="%.3f")})
        st.download_button("⬇ Download co-stocking rules",
                           show.to_csv(index=False).encode(), "co_stocking_rules.csv", "text/csv")

    with t3:
        lost = fc[~fc.beats_naive]
        a, b = st.columns(2)
        a.metric("SKUs where the model beats naive", f"{fc.beats_naive.sum():,} / {len(fc):,}")
        b.metric("Where it does not", f"{len(lost):,}")

        st.markdown('<div class="note">Every forecast is judged against a <b>naive baseline</b> '
                    '— next week equals this week. Where the model cannot beat that, it adds '
                    'complexity and risk for nothing. Knowing which SKUs those are is a '
                    'result, not a failure.</div>', unsafe_allow_html=True)
        st.write("")

        d = fc.merge(sku[["StockCode", "product", "class"]], on="StockCode", how="left")
        fig = px.scatter(d, x="mae_naive", y="mae_hw", color="beats_naive",
                         color_discrete_map={True: GREEN, False: RED},
                         hover_name="product", hover_data={"class": True},
                         labels={"mae_naive": "error — naive forecast",
                                 "mae_hw": "error — model", "beats_naive": "model wins"})
        lim = float(max(d.mae_naive.max(), d.mae_hw.max()))
        fig.add_shape(type="line", x0=0, y0=0, x1=lim, y1=lim,
                      line=dict(color=GREY, dash="dash"))
        style_fig(fig, 420)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Below the dashed line, the model wins. Above it, the naive forecast is "
                   "as good or better.")

st.divider()
st.caption(
    "Built from 1,014,751 transaction lines — Online Retail II, UCI Machine Learning "
    "Repository, CC BY 4.0. Reorder points are derived from demand and forecast error; the "
    "source data holds no stock-on-hand, so the policy was validated by simulation against "
    "held-out demand rather than against real inventory positions."
)
