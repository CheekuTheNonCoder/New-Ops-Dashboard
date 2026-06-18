"""
app.py — Enterprise Operations Intelligence Platform (v4.0)
Calculates overall support metrics and maps custom single-period dropdown filters.
Fixed: Implemented segment-aware separate KPIs and side-by-side matrices in Combined Mode.
"""
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import json
import os

from google_loader import load_sheet_data, SPREADSHEET_ID
from engine_loader import process_pipeline, generate_dynamic_periods
from engine_analytics import (
    compute_brand_summary, compute_product_summary,
    compute_cohort_report, compute_weekly_trends, top_kpis, raw_esc,
    compute_subcat_summary, HIGH_SUBCATS
)
from engine_export import generate_excel_report

st.set_page_config(
    page_title="Ops Intelligence Platform",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
html, body, [data-testid="stAppViewContainer"] { background: #0D1117 !important; }
[data-testid="stAppViewContainer"] > .main { background: #0D1117; }
.main .block-container { padding: 1rem 2rem 2rem 2rem !important; max-width: 100% !important; }
[data-testid="stSidebar"] { background: #161B26 !important; border-right: 1px solid #21262D !important; min-width: 260px !important; }
[data-testid="stSidebar"] * { color: #8B949E !important; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2 { color: #E6EDF3 !important; }
.stTabs [data-baseweb="tab-list"] { background: #161B26; border-radius: 8px; padding: 4px; border: 1px solid #21262D; }
.stTabs [data-baseweb="tab"] { color: #6E7681 !important; padding: 5px 14px !important; font-size: 12px !important; font-weight: 500 !important; }
.stTabs [aria-selected="true"] { background: #21262D !important; color: #E6EDF3 !important; }
.kpi { background: #161B26; border: 1px solid #21262D; border-radius: 8px; padding: 12px 14px; margin-bottom: 6px; min-height: 80px; }
.kpi.red { border-left: 3px solid #F85149; }
.kpi.amber { border-left: 3px solid #D29922; }
.kpi.green { border-left: 3px solid #3FB950; }
.kpi.blue { border-left: 3px solid #58A6FF; }
.kpi-lbl { font-size: 10px; font-weight: 600; color: #6E7681; text-transform: uppercase; margin: 0 0 4px; }
.kpi-val { font-size: 20px; font-weight: 700; color: #E6EDF3; margin: 0; }
.kpi-sub { font-size: 10px; color: #484F58; margin: 2px 0 0; }
.brow { background: #161B26; border: 1px solid #21262D; border-radius: 6px; padding: 8px; margin-bottom: 5px; font-size: 12px; }
.shdr { font-size: 11px; font-weight: 600; color: #6E7681; text-transform: uppercase; border-bottom: 1px solid #21262D; padding-bottom: 5px; margin: 16px 0 10px; }
.ai-box { background: #1F242C; border: 1px solid #30363D; border-radius: 8px; padding: 15px; color: #C9D1D9; font-size: 13px; line-height: 1.6; margin-top: 10px; }
</style>
""", unsafe_allow_html=True)


def kpi(label, value, sub="", color="blue"):
    st.markdown(f"""<div class="kpi {color}"><p class="kpi-lbl">{label}</p><p class="kpi-val">{value}</p>{'<p class="kpi-sub">'+sub+'</p>' if sub else ''}</div>""", unsafe_allow_html=True)


def handle_ai_error(e):
    err_msg = str(e)
    if "getaddrinfo failed" in err_msg or "11001" in err_msg:
        st.error("🔌 **Connection Issue:** Verify your system has active internet access.")
    elif "503" in err_msg or "Service Unavailable" in err_msg:
        st.error("⏳ **Temporary Timeout (503):** The model server is currently busy. Please retry.")
    elif "401" in err_msg or "Unauthorized" in err_msg:
        st.error("🔑 **Auth Key Failed (401):** Verify that your Google Gemini API Key is active.")
    else:
        st.error(f"⚠️ **AI Execution Error:** {err_msg}")


@st.cache_data(show_spinner=False)
def run_pipeline(del_df_raw, tick_df_raw):
    return process_pipeline(del_df_raw, tick_df_raw)


# ── SIDEBAR INTERFACE ──
with st.sidebar:
    st.markdown("## ⚙️ Data Ingestion Mode")
    source_mode = st.radio("Select Ingestion Mode", ["Google Sheets", "Local Upload"], index=0)
    
    if source_mode == "Google Sheets":
        st.markdown(f"**Spreadsheet ID:**\n`{SPREADSHEET_ID}`")
        if st.button("🔄 Sync & Reload Sheets"):
            st.cache_data.clear()
            st.rerun()
    else:
        del_file = st.file_uploader("Upload Delivered Orders", type=["xlsx", "xls"], key="del_up")
        tick_file = st.file_uploader("Upload Tickets Dump", type=["xlsx", "xls"], key="tik_up")
        
    st.divider()

    st.markdown("**Severity Threshold Metrics**")
    with st.expander("Configure Matrix Thresholds"):
        crit_del = st.number_input("Critical Min Deliveries", value=300, step=50)
        crit_esc = st.number_input("Critical Min Esc %", value=7.0, step=0.5)
        crit_tix = st.number_input("Critical Min Tickets", value=25, step=5)
        high_del = st.number_input("High Min Deliveries", value=200, step=50)
        high_esc = st.number_input("High Min Esc %", value=5.0, step=0.5)
        med_del  = st.number_input("Medium Min Deliveries", value=100, step=25)
        med_esc  = st.number_input("Medium Min Esc %", value=3.0, step=0.5)

    st.divider()
    ai_on = st.toggle("Enable AI Analysis Panel", value=False)
    api_key = ""
    if ai_on:
        try:
            api_key = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
        except:
            api_key = ""
        if not api_key:
            api_key = st.text_input("GCP Gemini API Key", type="password", help="Enter Google Gemini API Key")

    st.divider()
    st.caption("v4.0 • Production Release")


# ── INGESTION PIPELINES ──
if source_mode == "Google Sheets":
    try:
        del_df_raw, tick_df_raw = load_sheet_data(SPREADSHEET_ID)
        st.sidebar.success("✅ Synced with Google Sheets")
    except Exception as e:
        st.error(f"❌ Ingestion Error: {e}")
        st.stop()
else:
    if not del_file or not tick_file:
        st.markdown("## 📦 Operations Intelligence Platform")
        st.caption("Please upload Delivered Orders and Tickets Dump files in the sidebar to execute.")
        st.stop()
    try:
        del_df_raw = pd.read_excel(del_file)
        tick_df_raw = pd.read_excel(tick_file)
        st.sidebar.success("✅ Files uploaded successfully")
    except Exception as e:
        st.error(f"❌ File Parsing Error: {e}")
        st.stop()


# ── RUN CALCULATIONS ──
try:
    D = run_pipeline(del_df_raw, tick_df_raw)
except Exception as e:
    st.error(f"❌ Pipeline Execution Error: {e}")
    st.stop()

del_df = D["del_df"]
tick_df = D["tick_df"]
registry = D["registry"]
redist_sum = D["redist_summary"]

orig = D.get("original_ticket_count", 0)
final_c = D.get("final_ticket_count", 0)
val_ok = D.get("validation_ok", False)

# Dynamic available months parsing to prevent NameError on historical comparison tab
available_months = sorted(del_df["Delivery Month Sort"].dropna().unique())


# ── TIME INTELLIGENCE & FILTER INTERFACE ──
st.markdown("### 📊 Time Intelligence Filter")

# Generate period options strictly from the raw_date of uploaded data (No hardcoding)
period_options = generate_dynamic_periods(del_df, "raw_date")
selected_period = st.selectbox("Select Filter Period", period_options)

# Filter both dataframes dynamically based on selection
if selected_period == "All Data":
    f_del = del_df.copy()
    f_tick = tick_df.copy()
else:
    try:
        # Check if selected_period is a precise single date (e.g. "May 14, 2026")
        parsed_date = pd.to_datetime(selected_period, format="%B %d, %Y")
        f_del = del_df[pd.to_datetime(del_df["raw_date"], errors="coerce").dt.date == parsed_date.date()].copy()
        # Tickets strictly filtered by Ticket Creation Date for exact matching
        f_tick = tick_df[pd.to_datetime(tick_df["raw_date"], errors="coerce").dt.date == parsed_date.date()].copy()
    except Exception:
        # Fallback to Month matching (e.g. "May 2026")
        f_del = del_df[del_df["Delivery Month"] == selected_period].copy()
        # Tickets strictly filtered by Ticket Creation Month (Ticket Month) for 100% operational matching
        f_tick = tick_df[tick_df["Ticket Month"] == selected_period].copy()


# ── DATE DIAGNOSTICS FOR QUALITY ASSURANCE ──
if len(period_options) <= 1:
    with st.sidebar.expander("🛠️ Live Date Debugger (Empty Months Detected)", expanded=True):
        st.warning("⚠️ Checking Google Sheets format:")
        st.write("**Delivered Columns:**", list(del_df_raw.columns))
        if not del_df_raw.empty:
            st.write("**First 3 raw dates:**", del_df_raw.iloc[:3, 0].tolist())
        st.write("**Tickets Columns:**", list(tick_df_raw.columns))
        if not tick_df_raw.empty:
            st.write("**First 3 raw dates:**", tick_df_raw.iloc[:3, 0].tolist())


# ── OPERATIONS UNIVERSE SEGMENT SELECTOR ──
st.markdown("### 🔍 Segment Category Filter")
analysis_mode = st.radio(
    "Active Segment Filter",
    ["Post Delivery", "Pre Delivery", "Combined"],
    horizontal=True,
    help="POST limits orders to 'delivered' and matches post tickets; PRE includes all orders and matches pre tickets."
)

if analysis_mode == "Post Delivery":
    f_del_universe = f_del[f_del["is_delivered"] == True].copy()
    f_tick_universe = f_tick[f_tick["ticket_category"] == "POST_DELIVERY"].copy()
elif analysis_mode == "Pre Delivery":
    f_del_universe = f_del.copy()
    f_tick_universe = f_tick[f_tick["ticket_category"] == "PRE_DELIVERY"].copy()
else:
    f_del_universe = f_del.copy()
    f_tick_universe = f_tick.copy()


# ── RUN SEGMENT ANALYTICS ──
brand_sum = compute_brand_summary(f_del_universe, f_tick_universe, analysis_mode, crit_del, crit_esc, crit_tix, high_del, high_esc, med_del, med_esc)
prod_sum = compute_product_summary(f_del_universe, f_tick_universe, analysis_mode, crit_del, crit_esc, crit_tix, high_del, high_esc, med_del, med_esc)
cohort_report = compute_cohort_report(f_del_universe, f_tick_universe)
weeks_list = sorted(f_del_universe["Delivery Week"].unique())
weekly_trends = compute_weekly_trends(f_del_universe, f_tick_universe, weeks_list)
subcat_sum = compute_subcat_summary(f_tick_universe)

# Single Source of Truth KPIs: Delivered Orders always uses unique Order IDs (zop_id)
status_col = "order_status" if "order_status" in f_del_universe.columns else None

overall_orders_count = f_del_universe["order_id"].nunique() if not f_del_universe.empty else 0
overall_tickets_count = len(f_tick_universe)
overall_esc_rate = round((overall_tickets_count / max(overall_orders_count, 1)) * 100, 2)

subcat_col = "subcat_final" if "subcat_final" in f_tick_universe.columns else "raw_subcat"
defect_tickets_count = len(f_tick_universe[f_tick_universe[subcat_col].isin(HIGH_SUBCATS)]) if not f_tick_universe.empty else 0
overall_defect_rate = round((defect_tickets_count / max(overall_orders_count, 1)) * 100, 2)

kpis = top_kpis(brand_sum, prod_sum, subcat_sum, f_tick_universe, f_del_universe, weeks_list)


# ── HISTORICAL MOVEMENT COMPARISON ──
comp_df_brand = pd.DataFrame()
comp_df_prod = pd.DataFrame()
has_comparison = len(available_months) >= 2

if has_comparison:
    m_names = [m.strftime("%B %Y") for m in available_months]
    month_a = m_names[-2]
    month_b = m_names[-1]
    
    del_a = del_df[del_df["Delivery Month"] == month_a]
    tick_a = tick_df[tick_df["Delivery Month"] == month_a]
    del_b = del_df[del_df["Delivery Month"] == month_b]
    tick_b = tick_df[tick_df["Delivery Month"] == month_b]
    
    brand_a = compute_brand_summary(del_a, tick_a, analysis_mode, crit_del, crit_esc, crit_tix, high_del, high_esc, med_del, med_esc).set_index("brand")
    brand_b = compute_brand_summary(del_b, tick_b, analysis_mode, crit_del, crit_esc, crit_tix, high_del, high_esc, med_del, med_esc).set_index("brand")
    
    comp_df_brand = pd.DataFrame(index=sorted(list(set(brand_a.index) | set(brand_b.index))))
    comp_df_brand["Month A Esc %"] = comp_df_brand.index.map(brand_a["esc_pct"]).fillna(0.0)
    comp_df_brand["Month B Esc %"] = comp_df_brand.index.map(brand_b["esc_pct"]).fillna(0.0)
    comp_df_brand["Esc % Difference"] = (comp_df_brand["Month B Esc %"] - comp_df_brand["Month A Esc %"]).round(2)
    comp_df_brand["Esc Movement Status"] = comp_df_brand["Esc % Difference"].apply(
        lambda x: "🚨 INCREASE" if x > 1.0 else "✅ DECREASE" if x < -1.0 else "→ STABLE"
    )
    comp_df_brand = comp_df_brand.reset_index().rename(columns={"index": "Brand"})

    prod_a = compute_product_summary(del_a, tick_a, analysis_mode, crit_del, crit_esc, crit_tix, high_del, high_esc, med_del, med_esc).set_index("brand_product")
    prod_b = compute_product_summary(del_b, tick_b, analysis_mode, crit_del, crit_esc, crit_tix, high_del, high_esc, med_del, med_esc).set_index("brand_product")
    
    comp_df_prod = pd.DataFrame(index=sorted(list(set(prod_a.index) | set(prod_b.index))))
    comp_df_prod["Month A Esc %"] = comp_df_prod.index.map(prod_a["esc_pct"]).fillna(0.0)
    comp_df_prod["Month B Esc %"] = comp_df_prod.index.map(prod_b["esc_pct"]).fillna(0.0)
    comp_df_prod["Esc % Difference"] = (comp_df_prod["Month B Esc %"] - comp_df_prod["Month A Esc %"]).round(2)
    comp_df_prod["Esc Movement Status"] = comp_df_prod["Esc % Difference"].apply(
        lambda x: "🚨 INCREASE" if x > 1.0 else "✅ DECREASE" if x < -1.0 else "→ STABLE"
    )
    comp_df_prod = comp_df_prod.reset_index().rename(columns={"index": "brand_product"})
    comp_df_prod["Brand"] = comp_df_prod["brand_product"].apply(lambda x: x.split(" | ")[0] if " | " in str(x) else str(x))
    comp_df_prod["Product"] = comp_df_prod["brand_product"].apply(lambda x: x.split(" | ")[1] if " | " in str(x) else "")
    comp_df_prod = comp_df_prod[["Brand", "Product", "Month A Esc %", "Month B Esc %", "Esc % Difference", "Esc Movement Status"]]


# ── REPORT EXPORTER TRIGGER ──
xl_data = generate_excel_report(
    kpis, brand_sum, prod_sum, subcat_sum,
    weekly_trends, redist_sum, cohort_report, comp_df_brand, comp_df_prod,
    registry, f_tick, f_del,
    orig_tickets=orig, final_tickets=final_c, val_ok=val_ok, period=str(selected_period)
)

st.sidebar.download_button(
    "⬇️ Export Excel Report", data=xl_data,
    file_name=f"OpsIntel_Report_{datetime.now().strftime('%Y%m%d')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True
)


# ── KPI METRICS DISPLAY ──
st.markdown("### 📊 Active Segment Performance Overview")

if analysis_mode == "Combined":
    # Under Combined Mode, calculate and display BOTH metrics separately
    if status_col:
        post_orders_count = f_del_universe[f_del_universe[status_col].astype(str).str.strip().str.lower() == "delivered"]["order_id"].nunique()
    else:
        post_orders_count = f_del_universe["order_id"].nunique()
    pre_orders_count = f_del_universe["order_id"].nunique()
    
    post_tickets_count = len(f_tick_universe[f_tick_universe["ticket_category"] == "POST_DELIVERY"])
    pre_tickets_count = len(f_tick_universe[f_tick_universe["ticket_category"] == "PRE_DELIVERY"])
    
    post_esc_rate = round((post_tickets_count / max(post_orders_count, 1)) * 100, 2)
    pre_esc_rate = round((pre_tickets_count / max(pre_orders_count, 1)) * 100, 2)
    
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1: kpi("Delivered Orders", f"{post_orders_count:,}", "Post Denominator", "blue")
    with c2: kpi("Total Orders", f"{pre_orders_count:,}", "Pre Denominator", "blue")
    with c3: kpi("Post Tickets", f"{post_tickets_count:,}", "Post Numerator", "red")
    with c4: kpi("Pre Tickets", f"{pre_tickets_count:,}", "Pre Numerator", "red")
    with c5: kpi("Post Escalation %", f"{post_esc_rate}%", "Post Tickets ÷ Delivered", "amber" if post_esc_rate >= 3.0 else "green")
    with c6: kpi("Pre Escalation %", f"{pre_esc_rate}%", "Pre Tickets ÷ Total", "amber" if pre_esc_rate >= 3.0 else "green")
else:
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: 
        lbl_o = "Delivered Orders" if analysis_mode == "Post Delivery" else "Total Orders"
        kpi(lbl_o, f"{overall_orders_count:,}", "Unique Order IDs from dynamic status rules.", "blue")
    with c2: 
        kpi("Tickets", f"{overall_tickets_count:,}", "Filtered universe numerator.", "red")
    with c3: 
        lbl_esc_name = "Post Escalation %" if analysis_mode == "Post Delivery" else "Pre Escalation %"
        kpi(lbl_esc_name, f"{overall_esc_rate}%", "Support tickets ÷ orders.", "amber" if overall_esc_rate >= 3.0 else "green")
    with c4: 
        lbl_def_name = "Post Defect %" if analysis_mode == "Post Delivery" else "Pre Defect %"
        kpi(lbl_def_name, f"{overall_defect_rate}%", "Quality issues ÷ orders.", "red" if overall_defect_rate >= 1.5 else "green")
    with c5: 
        kpi("Peak Week", str(kpis['spike_week']), "Highest volume week.", "purple")

st.divider()


# ── EXECUTIVE RISK OVERVIEW ROWS ──
c_left, c_right = st.columns(2)
with c_left:
    st.markdown('<p class="shdr">Top Escalation Risk Brand Profiles</p>', unsafe_allow_html=True)
    if not brand_sum.empty:
        for _, row in brand_sum.head(3).iterrows():
            st.markdown(
                f"""<div class="brow">
                    <b style="color:#F85149">{row['brand']}</b>
                    <span style="float:right;color:#E6EDF3"><b>{row['esc_pct']:.2f}% Esc %</b> ({int(row['tickets']):,} tickets)</span>
                    <br><small style="color:#8B949E">Primary Issue: {row['Top Escalation Driver']} | Defect Rate: {row['defect_rate']:.2f}%</small>
                </div>""", 
                unsafe_allow_html=True
            )
with c_right:
    st.markdown('<p class="shdr">Top Support Driver Subcategories</p>', unsafe_allow_html=True)
    if not subcat_sum.empty:
        for _, row in subcat_sum.head(3).iterrows():
            st.markdown(
                f"""<div class="brow">
                    <b style="color:#58A6FF">{row['subcat_final']}</b>
                    <span style="float:right;color:#E6EDF3"><b>{row['count']:,} tickets</b> ({row['pct']:.1f}%)</span>
                    <br><small style="color:#8B949E">Classification Tier: {row['tier']}</small>
                </div>""", 
                unsafe_allow_html=True
            )

st.divider()


# ── TAB SYSTEM ──
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "🏷️ Brand Intel", "📦 Product Intel", "📅 Weekly Trends",
    "📊 Issue Breakdown", "📈 Month Comparison", "📋 Validation Panel", "🗺️ Redistribution Audit", "🤖 AI Insights"
])

# TAB 1: Brand Intel
with tab1:
    st.markdown('<p class="shdr">Brand Performance Matrix</p>', unsafe_allow_html=True)
    b_fa, b_fb, b_fc = st.columns(3)
    with b_fa:
        b_imp_f = st.multiselect("Impact Level Filter", ["CRITICAL", "HIGH", "MEDIUM", "LOW"], default=["CRITICAL", "HIGH", "MEDIUM", "LOW"], key="b_imp_tab")
    with b_fb:
        b_sort_choice = st.selectbox("Sort Matrix By", [
            "Highest Tickets", "Lowest Tickets", "Highest Esc %", "Lowest Esc %",
            "Highest Orders", "Lowest Orders", "A → Z"
        ], key="b_sort_tab")
    with b_fc:
        b_min_del = st.number_input("Minimum Orders Threshold", value=0, step=50, key="b_min_tab")
        
    disp_b = brand_sum[brand_sum["impact"].isin(b_imp_f)].copy() if not brand_sum.empty else pd.DataFrame()
    if b_min_del > 0 and not disp_b.empty:
        disp_b = disp_b[disp_b["delivered"] >= b_min_del]
        
    if not disp_b.empty:
        if b_sort_choice == "Highest Tickets":
            disp_b = disp_b.sort_values("tickets", ascending=False)
        elif b_sort_choice == "Lowest Tickets":
            disp_b = disp_b.sort_values("tickets", ascending=True)
        elif b_sort_choice == "Highest Esc %":
            disp_b = disp_b.sort_values("esc_pct", ascending=False)
        elif b_sort_choice == "Lowest Esc %":
            disp_b = disp_b.sort_values("esc_pct", ascending=True)
        elif b_sort_choice == "Highest Orders":
            disp_b = disp_b.sort_values("delivered", ascending=False)
        elif b_sort_choice == "Lowest Orders":
            disp_b = disp_b.sort_values("delivered", ascending=True)
        elif b_sort_choice == "A → Z":
            disp_b = disp_b.sort_values("brand", ascending=True)

        if analysis_mode == "Combined":
            st.dataframe(disp_b[["brand", "delivered_pre", "delivered_post", "tickets_pre", "tickets_post", "pre_esc_pct", "post_esc_pct", "post_defect_rate", "impact"]], use_container_width=True)
        else:
            st.dataframe(disp_b[["brand", "delivered", "tickets", "esc_pct", "defect_rate", "weighted_esc", "confidence", "Top Escalation Driver", "impact"]], use_container_width=True)
    else:
        st.info("No brand profiles match selected filters.")

    st.markdown('<p class="shdr">Individual Brand Analyzer</p>', unsafe_allow_html=True)
    if not brand_sum.empty:
        sel_b = st.selectbox("Select Brand Profile", sorted(brand_sum["brand"].unique()), key="drill_brand")
        b_row = brand_sum[brand_sum["brand"] == sel_b].iloc[0]
        
        bd1, bd2, bd3, bd4, bd5, bd6 = st.columns(6)
        with bd1: kpi("Orders Count", f"{int(b_row['delivered']):,}", color="blue")
        with bd2: kpi("Tickets Count", f"{int(b_row['tickets']):,}", color="red")
        with bd3: kpi("Escalation Rate %", f"{b_row['esc_pct']:.2f}%", color="amber")
        with bd4: kpi("Weighted Esc %", f"{b_row['weighted_esc']:.2f}%", color="purple")
        with bd5: kpi("Confidence %", f"{int(b_row['confidence'])}%", color="green")
        with bd6: kpi("Defect Rate %", f"{b_row['defect_rate']:.2f}%", color="red" if b_row['defect_rate'] >= 1.5 else "green")
        
        b_left, b_right = st.columns(2)
        with b_left:
            st.markdown("**Top Associated Products**")
            bp = prod_sum[prod_sum["brand"] == sel_b].head(10)[["canonical_product", "delivered", "tickets", "esc_pct", "impact"]].copy() if not prod_sum.empty else pd.DataFrame()
            st.dataframe(bp, use_container_width=True)
        with b_right:
            st.markdown("**Core Issues Categories**")
            bi = f_tick_universe[f_tick_universe["brand"] == sel_b].groupby("subcat_final").size().reset_index(name="Tickets").sort_values("Tickets", ascending=False) if not f_tick_universe.empty else pd.DataFrame()
            st.dataframe(bi, use_container_width=True)

# TAB 2: Product Intel
with tab2:
    st.markdown('<p class="shdr">Product Performance Matrix</p>', unsafe_allow_html=True)
    p_fa, p_fb, p_fc = st.columns(3)
    with p_fa:
        p_brand_f = st.multiselect("Filter by Brand Profiles", sorted(prod_sum["brand"].unique()) if not prod_sum.empty else [], key="p_brand_tab")
    with p_fb:
        p_imp_f = st.multiselect("Filter by Product Impact", ["CRITICAL", "HIGH", "MEDIUM", "LOW"], default=["CRITICAL", "HIGH", "MEDIUM", "LOW"], key="p_imp_tab")
    with p_fc:
        p_min_del = st.number_input("Minimum Products Volume Threshold", value=0, step=50, key="p_min_tab")
        
    disp_p = prod_sum[prod_sum["impact"].isin(p_imp_f)].copy() if not prod_sum.empty else pd.DataFrame()
    if p_brand_f and not disp_p.empty:
        disp_p = disp_p[disp_p["brand"].isin(p_brand_f)]
    if p_min_del > 0 and not disp_p.empty:
        disp_p = disp_p[disp_p["delivered"] >= p_min_del]
        
    if not disp_p.empty:
        if analysis_mode == "Combined":
            st.dataframe(disp_p[["brand", "canonical_product", "delivered_pre", "delivered_post", "tickets_pre", "tickets_post", "pre_esc_pct", "post_esc_pct", "Ticket Aging Category", "impact"]], use_container_width=True)
        else:
            st.dataframe(disp_p[["brand", "canonical_product", "delivered", "tickets", "esc_pct", "Primary Ticket Source Month", "Same Month Tickets", "Previous Month Tickets", "Older Tickets", "Ticket Aging Category", "impact"]], use_container_width=True)
    else:
        st.info("No product profiles match selected filters.")

    st.markdown('<p class="shdr">Product Group Analyzer</p>', unsafe_allow_html=True)
    if not prod_sum.empty:
        pd_b = st.selectbox("Select Brand for Product Analysis", sorted(prod_sum["brand"].unique()), key="p_drill_brand")
        pd_p_opts = sorted(prod_sum[prod_sum["brand"] == pd_b]["canonical_product"].unique())
        
        if pd_p_opts:
            pd_p = st.selectbox("Select Product Model Group", pd_p_opts, key="p_drill_product")
            p_row = prod_sum[(prod_sum["brand"] == pd_b) & (prod_sum["canonical_product"] == pd_p)].iloc[0]
            
            pd1, pd2, pd3, pd4 = st.columns(4)
            with pd1: kpi("Orders Volume", f"{int(p_row['delivered']):,}", color="blue")
            with pd2: kpi("Tickets Count", f"{int(p_row['tickets']):,}", color="red")
            with pd3: kpi("Escalation Rate %", f"{p_row['esc_pct']:.2f}%", color="amber")
            with pd4: kpi("Confidence %", f"{int(p_row['confidence'])}%", color="green")
            
            st.markdown("**Associated Support Issues Categories**")
            p_bi = f_tick_universe[(f_tick_universe["brand"] == pd_b) & (f_tick_universe["canonical_product"] == pd_p)].groupby("subcat_final").size().reset_index(name="Tickets").sort_values("Tickets", ascending=False) if not f_tick_universe.empty else pd.DataFrame()
            st.dataframe(p_bi, use_container_width=True)

    # Product Registry Mapping log
    st.markdown('<p class="shdr">🛠️ Product Registry Mapping Audit Log</p>', unsafe_allow_html=True)
    with st.expander("View Normalization Mapping Logs", expanded=False):
        if hasattr(registry, "debug_log") and registry.debug_log:
            st.dataframe(pd.DataFrame(registry.debug_log).style.hide(axis="index"), use_container_width=True, height=350)
        else:
            st.info("No normalization activity logs recorded.")

# TAB 3: Weekly Trends
with tab3:
    st.markdown('<p class="shdr">Weekly WoW Escalation Performance</p>', unsafe_allow_html=True)
    if not weekly_trends.empty:
        st.dataframe(weekly_trends, use_container_width=True)
    else:
        st.info("No weekly performance summaries found.")

# TAB 4: Issue Breakdown
with tab4:
    st.markdown('<p class="shdr">Support Subcategory Severity Distribution</p>', unsafe_allow_html=True)
    if not subcat_sum.empty:
        st.dataframe(subcat_sum, use_container_width=True)
    else:
        st.info("No recorded support tickets found.")

# TAB 5: Month Comparison
with tab5:
    st.markdown('<p class="shdr">Chronological Delivery Cohorts</p>', unsafe_allow_html=True)
    if not cohort_report.empty:
        st.dataframe(cohort_report, use_container_width=True)
    else:
        st.info("No cohort summaries found.")
    
    if not has_comparison:
        st.info("⚠️ At least 2 active months are required to generate comparison matrix sheets.")
    else:
        st.markdown('<p class="shdr">Month-over-Month Comparison Analysis</p>', unsafe_allow_html=True)
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            comp_brand_filter = st.multiselect(
                "Filter Matrix by Brand Profiles", 
                sorted(list(set(comp_df_brand["Brand"].unique()) | set(comp_df_prod["Brand"].unique()))) if not comp_df_brand.empty else []
            )
        with col_c2:
            comp_sort_choice = st.selectbox(
                "Sort Matrix",
                ["A → Z", "Highest Variance", "Lowest Variance"]
            )
            
        disp_comp_brand = comp_df_brand.copy() if not comp_df_brand.empty else pd.DataFrame()
        disp_comp_prod = comp_df_prod.copy() if not comp_df_prod.empty else pd.DataFrame()
        
        if comp_brand_filter:
            if not disp_comp_brand.empty:
                disp_comp_brand = disp_comp_brand[disp_comp_brand["Brand"].isin(comp_brand_filter)]
            if not disp_comp_prod.empty:
                disp_comp_prod = disp_comp_prod[disp_comp_prod["Brand"].isin(comp_brand_filter)]
            
        if not disp_comp_brand.empty:
            if comp_sort_choice == "A → Z":
                disp_comp_brand = disp_comp_brand.sort_values("Brand", ascending=True)
                disp_comp_prod = disp_comp_prod.sort_values(["Brand", "Product"], ascending=True)
            elif comp_sort_choice == "Highest Variance":
                disp_comp_brand = disp_comp_brand.sort_values("Esc % Difference", ascending=False)
                disp_comp_prod = disp_comp_prod.sort_values("Esc % Difference", ascending=False)
            elif comp_sort_choice == "Lowest Variance":
                disp_comp_brand = disp_comp_brand.sort_values("Esc % Difference", ascending=True)
                disp_comp_prod = disp_comp_prod.sort_values("Esc % Difference", ascending=True)

            st.markdown(f'<p class="shdr">Brand Level Variance ({month_a} vs {month_b})</p>', unsafe_allow_html=True)
            st.dataframe(disp_comp_brand, use_container_width=True)
            st.markdown(f'<p class="shdr">Product Level Variance ({month_a} vs {month_b})</p>', unsafe_allow_html=True)
            st.dataframe(disp_comp_prod, use_container_width=True)

# TAB 6: Validation Panel
with tab6:
    st.markdown('<p class="shdr">System Audit & Reconciliation Ledger</p>', unsafe_allow_html=True)
    
    validation_status = "PASS ✅" if val_ok else "FAIL ❌"
    
    st.markdown("**Chronological Date Coercion Quality Report**")
    dq1, dq2 = st.columns(2)
    with dq1: kpi("Delivered Date Coerced NaT", f"{D['invalid_del_dates']:,}", "Null or pre-1975 dates resolved.", "blue")
    with dq2: kpi("Ticket Date Coerced NaT", f"{D['invalid_tick_dates']:,}", "Null or pre-1975 dates resolved.", "red")
    
    st.markdown("**Operational Ticket Ledger Balance Audit**")
    v1, v2, v3, v4, v5, v6, v7 = st.columns(7)
    with v1: kpi("Raw Ingested Tickets", f"{orig:,}", "Count from Google Sheet.", "blue")
    with v2: kpi("Final Processed Tickets", f"{final_c:,}", "Count from pipeline output.", "green" if val_ok else "red")
    with v3: kpi("Brand Unmapped", f"{D['n_unmapped_brand']:,}", "Volume apportioned.", "purple")
    with v4: kpi("Need Details Base", f"{D['n_need_details']:,}", "Placeholders re-mapped.", "purple")
    v_diff = abs(orig - final_c)
    with v5: kpi("Subcat Not Found", f"{D['n_not_found_subcat']:,}", "Placeholders re-mapped.", "purple")
    with v6: kpi("Ledger Diff", f"{v_diff}", "Must be exactly 0.", "green" if v_diff == 0 else "red")
    with v7: kpi("Ledger Sync Check", str(validation_status), "Balanced logic check.", "green" if val_ok else "red")
    
    st.markdown("**Ticket Classification Log**")
    ac1, ac2 = st.columns(2)
    with ac1:
        st.markdown("**Raw Ingested support categories**")
        st.write(D["raw_cat_counts"])
    with ac2:
        st.markdown("**Standardized operational categories**")
        st.write(D["norm_cat_counts"])

# TAB 7: Redistribution Audit
with tab7:
    st.markdown('<p class="shdr">Redistribution Audit Log Ledger</p>', unsafe_allow_html=True)
    if not redist_sum.empty:
        st.dataframe(redist_sum, use_container_width=True)
    else:
        st.info("No unmapped redistribution activities recorded.")

# TAB 8: AI Insights
with tab8:
    st.markdown('<p class="shdr">Cognitive Operational Insights & Recommendations</p>', unsafe_allow_html=True)
    if not ai_on:
        st.info("AI Analysis is deactivated. Toggle 'Enable AI Analysis' in the sidebar.")
    elif not api_key:
        st.warning("Please enter your Google Gemini API Key in the sidebar.")
    else:
        def call_gemini(prompt, key):
            import urllib.request
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key.strip()}"
            body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req) as r:
                res_data = json.loads(r.read())
                return res_data["candidates"][0]["content"]["parts"][0]["text"]

        top10b = brand_sum.head(10)[["brand", "delivered", "tickets", "esc_pct"]].to_dict("records") if not brand_sum.empty else []
        top10p = prod_sum.head(10)[["brand", "canonical_product", "delivered", "tickets", "esc_pct"]].to_dict("records") if not prod_sum.empty else []
        top_i  = f_tick_universe.groupby("subcat_final").size().reset_index(name="count").sort_values("count", ascending=False).head(8).to_dict("records") if not f_tick_universe.empty else []

        ai1, ai2 = st.columns(2)
        with ai1:
            st.markdown("#### 📑 Summary Generator")
            if st.button("Generate Strategic Analysis", key="ai_exec"):
                with st.spinner("Analysing performance matrix..."):
                    try:
                        out = call_gemini(f"""Senior Operational Analyst.
Active Analysis Universe Mode: {analysis_mode}
Context: {overall_orders_count:,} unique orders, {overall_tickets_count:,} tickets, overall escalation {overall_esc_rate}%.
Top Brands: {json.dumps(top10b)}
Top Products: {json.dumps(top10p)}
Top Issues Categories: {json.dumps(top_i)}
Please construct: 1) Executive Performance Summary, 2) Critical Brand Profiles, 3) Primary Root Causes, 4) Product Focus Area, 5) Five Immediate Operational Recommendations.
Ensure your recommendations reference metrics from the dataset. Maintain a business-friendly, professional tone.""", api_key)
                        st.markdown(f'<div class="ai-box">{out}</div>', unsafe_allow_html=True)
                    except Exception as e:
                        handle_ai_error(e)
        with ai2:
            st.markdown("#### 💬 Ask Operational Expert")
            q = st.text_area("Question", placeholder="e.g. Which specific product drivers are causing the highest defect spikes this month?", height=90, key="ai_q")
            if st.button("Query Expert", key="ai_ask"):
                if q.strip():
                    with st.spinner("Processing scenario..."):
                        try:
                            out = call_gemini(f"""Senior Escalation Engineer.
Active Analysis Universe Mode: {analysis_mode}
{overall_orders_count:,} unique orders, {overall_tickets_count:,} tickets.
Top Brands: {json.dumps(top10b)}
Top Products: {json.dumps(top10p)}
Top Issues: {json.dumps(top_i)}
User Query: {q}
Respond directly to the user's query using calculations and metrics from the provided data. Avoid speculation.""", api_key)
                            st.markdown(f'<div class="ai-box">{out}</div>', unsafe_allow_html=True)
                        except Exception as e:
                            handle_ai_error(e)

        st.divider()
        st.markdown("#### 🏷️ Individual Brand Intelligence Deep Dive")
        ai_b = st.selectbox("Select Brand for Deep Dive", brand_sum["brand"].tolist() if not brand_sum.empty else [], key="ai_bd")
        if st.button("Generate Brand Intelligence Report", key="ai_bd_btn"):
            bd  = brand_sum[brand_sum["brand"]==ai_b].to_dict("records")
            bp2 = prod_sum[prod_sum["brand"]==ai_b].head(8)[["canonical_product","delivered","tickets","esc_pct"]].to_dict("records") if not prod_sum.empty else []
            bi3 = f_tick_universe[f_tick_universe["brand"]==ai_b]["subcat_final"].value_counts().head(6).to_dict() if not f_tick_universe.empty else {}
            with st.spinner(f"Compiling brand dossier for {ai_b}..."):
                try:
                    out = call_gemini(f"""Brand Health Analyst.
Target Profile: {ai_b}
Brand Summary: {json.dumps(bd)}
Brand Products: {json.dumps(bp2)}
Support Drivers: {json.dumps(bi3)}
Active Universe Segment: {analysis_mode}
Please deliver: 1) Strategic Assessment, 2) Core Vulnerabilities, 3) Tactical Product Defect Deep Dive, 4) Operational Response Strategy.""", api_key)
                    st.markdown(f'<div class="ai-box">{out}</div>', unsafe_allow_html=True)
                except Exception as e:
                    handle_ai_error(e)
