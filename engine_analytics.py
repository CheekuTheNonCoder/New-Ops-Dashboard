"""
engine_analytics.py — Advanced Operational & Segment Scoring Engine (v4.0)
Calculates brand/product escalation metrics using exact raw row counts (denominators).
Strictly avoids nunique() and deduplication to maintain direct operational alignment.
"""
import pandas as pd
import numpy as np

# Subcategory severity mappings
HIGH_SUBCATS = ["Defective Product", "Damaged Product", "Low Quality Product", "Order Delay", "Order Not Shipped"]
MEDIUM_SUBCATS = ["Wrong Product Delivered", "Missing Items", "Refund Post Delivery", "Cancellation Request", "Tracking Query"]
LOW_SUBCATS = ["Colour Issue", "Size issue", "Quantity Mismatch", "Order Modification", "Address Change", "Payment Issue", "Order Confirmation Issue"]


def confidence_factor(delivered):
    """Returns a confidence multiplier 0.0–1.0 based on order volume."""
    if delivered >= 500:  return 1.00
    if delivered >= 300:  return 0.90
    if delivered >= 200:  return 0.80
    if delivered >= 100:  return 0.65
    if delivered >= 50:   return 0.45
    if delivered >= 20:   return 0.25
    return 0.10


def weighted_esc(tickets, delivered):
    """Confidence-adjusted escalation percentage."""
    if delivered <= 0:
        return 0.0
    raw = (tickets / delivered) * 100
    cf = confidence_factor(delivered)
    return round(raw * cf, 2)


def raw_esc(tickets, delivered):
    if delivered <= 0:
        return 0.0
    return round((tickets / delivered) * 100, 2)


def compute_brand_summary(del_df, tick_df, analysis_mode="Post Delivery",
                          crit_del=300, crit_esc=7.0, crit_tix=25,
                          high_del=200, high_esc=5.0,
                          med_del=100, med_esc=3.0):
    """Calculates active brand profiles with exact raw row count denominators."""
    subcat_col = "subcat_final" if "subcat_final" in tick_df.columns else "raw_subcat"
    status_col = "order_status" if "order_status" in del_df.columns else None
    
    if analysis_mode == "Post Delivery":
        # Denominator: Raw Delivered Orders rows count (Status == Delivered)
        if status_col:
            orders_universe = del_df[del_df[status_col].astype(str).str.strip().str.lower() == "delivered"]
        else:
            orders_universe = del_df
            
        ticks_universe = tick_df[tick_df["ticket_category"] == "POST_DELIVERY"] if not tick_df.empty else tick_df
        
        brand_del = orders_universe.groupby("brand").size().reset_index(name="delivered")
        brand_tick = ticks_universe.groupby("brand").size().reset_index(name="tickets")
        
        defect_tix = ticks_universe[ticks_universe[subcat_col].isin(HIGH_SUBCATS)] if not ticks_universe.empty else ticks_universe
        brand_defect = defect_tix.groupby("brand").size().reset_index(name="defect_tickets")
        
        df = brand_del.merge(brand_tick, on="brand", how="outer").fillna(0)
        df = df.merge(brand_defect, on="brand", how="left").fillna(0)
        
        df["brand"] = df["brand"].astype(str)
        df["delivered"] = df["delivered"].astype(int)
        df["tickets"] = df["tickets"].astype(int)
        df["defect_tickets"] = df["defect_tickets"].fillna(0).astype(int)
        
        df["esc_pct"] = df.apply(lambda r: raw_esc(r["tickets"], r["delivered"]), axis=1)
        df["defect_rate"] = df.apply(lambda r: raw_esc(r["defect_tickets"], r["delivered"]), axis=1)
        df["weighted_esc"] = df.apply(lambda r: weighted_esc(r["tickets"], r["delivered"]), axis=1)
        df["confidence"] = df["delivered"].apply(lambda d: round(confidence_factor(d) * 100))
        
        df["del_share"] = (df["delivered"] / max(df["delivered"].sum(), 1) * 100).round(1)
        df["tick_share"] = (df["tickets"] / max(df["tickets"].sum(), 1) * 100).round(1)
        
    elif analysis_mode == "Pre Delivery":
        # Denominator: Raw Orders rows count across all statuses
        orders_universe = del_df
        ticks_universe = tick_df[tick_df["ticket_category"] == "PRE_DELIVERY"] if not tick_df.empty else tick_df
        
        brand_del = orders_universe.groupby("brand").size().reset_index(name="delivered")
        brand_tick = ticks_universe.groupby("brand").size().reset_index(name="tickets")
        
        df = brand_del.merge(brand_tick, on="brand", how="outer").fillna(0)
        df["brand"] = df["brand"].astype(str)
        df["delivered"] = df["delivered"].astype(int)
        df["tickets"] = df["tickets"].astype(int)
        
        df["esc_pct"] = df.apply(lambda r: raw_esc(r["tickets"], r["delivered"]), axis=1)
        df["defect_rate"] = 0.0
        df["weighted_esc"] = df.apply(lambda r: weighted_esc(r["tickets"], r["delivered"]), axis=1)
        df["confidence"] = df["delivered"].apply(lambda d: round(confidence_factor(d) * 100))
        
        df["del_share"] = (df["delivered"] / max(df["delivered"].sum(), 1) * 100).round(1)
        df["tick_share"] = (df["tickets"] / max(df["tickets"].sum(), 1) * 100).round(1)
        
    else:  # Combined Mode (Calculates BOTH Pre and Post separately)
        if status_col:
            del_orders = del_df[del_df[status_col].astype(str).str.strip().str.lower() == "delivered"]
        else:
            del_orders = del_df
            
        post_tix = tick_df[tick_df["ticket_category"] == "POST_DELIVERY"] if not tick_df.empty else tick_df
        post_defect_tix = post_tix[post_tix[subcat_col].isin(HIGH_SUBCATS)] if not post_tix.empty else post_tix
        
        all_orders = del_df
        pre_tix = tick_df[tick_df["ticket_category"] == "PRE_DELIVERY"] if not tick_df.empty else tick_df
        
        brand_del_post = del_orders.groupby("brand").size().reset_index(name="delivered_post")
        brand_tick_post = post_tix.groupby("brand").size().reset_index(name="tickets_post")
        brand_defect_post = post_defect_tix.groupby("brand").size().reset_index(name="defect_tickets_post")
        
        brand_del_pre = all_orders.groupby("brand").size().reset_index(name="delivered_pre")
        brand_tick_pre = pre_tix.groupby("brand").size().reset_index(name="tickets_pre")
        
        # Merge segments cleanly
        df_comb = brand_del_pre.merge(brand_del_post, on="brand", how="outer").fillna(0)
        df_comb = df_comb.merge(brand_tick_pre, on="brand", how="outer").fillna(0)
        df_comb = df_comb.merge(brand_tick_post, on="brand", how="outer").fillna(0)
        df_comb = df_comb.merge(brand_defect_post, on="brand", how="left").fillna(0)
        
        df_comb["brand"] = df_comb["brand"].astype(str)
        df_comb["delivered_pre"] = df_comb["delivered_pre"].astype(int)
        df_comb["delivered_post"] = df_comb["delivered_post"].astype(int)
        df_comb["tickets_pre"] = df_comb["tickets_pre"].astype(int)
        df_comb["tickets_post"] = df_comb["tickets_post"].astype(int)
        df_comb["defect_tickets_post"] = df_comb["defect_tickets_post"].fillna(0).astype(int)
        
        df_comb["pre_esc_pct"] = df_comb.apply(lambda r: raw_esc(r["tickets_pre"], r["delivered_pre"]), axis=1)
        df_comb["post_esc_pct"] = df_comb.apply(lambda r: raw_esc(r["tickets_post"], r["delivered_post"]), axis=1)
        df_comb["post_defect_rate"] = df_comb.apply(lambda r: raw_esc(r["defect_tickets_post"], r["delivered_post"]), axis=1)
        
        # Unified fallback fields for backwards UI layout compatibility
        df_comb["delivered"] = df_comb["delivered_pre"]
        df_comb["tickets"] = df_comb["tickets_pre"] + df_comb["tickets_post"]
        df_comb["esc_pct"] = df_comb["post_esc_pct"]
        df_comb["defect_rate"] = df_comb["post_defect_rate"]
        df_comb["weighted_esc"] = df_comb.apply(lambda r: weighted_esc(r["tickets"], r["delivered"]), axis=1)
        df_comb["confidence"] = df_comb["delivered"].apply(lambda d: round(confidence_factor(d) * 100))
        df_comb["del_share"] = (df_comb["delivered"] / max(df_comb["delivered"].sum(), 1) * 100).round(1)
        df_comb["tick_share"] = (df_comb["tickets"] / max(df_comb["tickets"].sum(), 1) * 100).round(1)
        df = df_comb

    top_drivers = {}
    for b in df["brand"]:
        b_tix = tick_df[tick_df["brand"] == b]
        if not b_tix.empty:
            top_drivers[b] = b_tix[subcat_col].value_counts().index[0]
        else:
            top_drivers[b] = "N/A"
    df["Top Escalation Driver"] = df["brand"].map(top_drivers)
    
    # Impact score mapping
    if analysis_mode == "Post Delivery" or analysis_mode == "Pre Delivery":
        df["impact"] = df.apply(
            lambda r: "CRITICAL" if r["delivered"] >= crit_del and r["esc_pct"] >= crit_esc and r["tickets"] >= crit_tix 
            else "HIGH" if r["delivered"] >= high_del and r["esc_pct"] >= high_esc
            else "MEDIUM" if r["delivered"] >= med_del and r["esc_pct"] >= med_esc
            else "LOW", axis=1
        )
    else:  # Combined Mode Impact triggers
        df["impact"] = df.apply(
            lambda r: "CRITICAL" if (r["post_esc_pct"] >= crit_esc and r["tickets_post"] >= crit_tix) or (r["pre_esc_pct"] >= crit_esc and r["tickets_pre"] >= crit_tix)
            else "HIGH" if r["post_esc_pct"] >= high_esc or r["pre_esc_pct"] >= high_esc
            else "MEDIUM" if r["post_esc_pct"] >= med_esc or r["pre_esc_pct"] >= med_esc
            else "LOW", axis=1
        )
        
    return df.sort_values("tickets", ascending=False).reset_index(drop=True)


def compute_product_summary(del_df, tick_df, analysis_mode="Post Delivery",
                             crit_del=300, crit_esc=7.0, crit_tix=25,
                             high_del=200, high_esc=5.0,
                             med_del=100, med_esc=3.0):
    """Detailed Product-level matrix calculations using raw row count denominators."""
    if analysis_mode == "Post Delivery":
        status_col = "order_status" if "order_status" in del_df.columns else None
        if status_col:
            orders_universe = del_df[del_df[status_col].astype(str).str.strip().str.lower() == "delivered"]
        else:
            orders_universe = del_df
        ticks_universe = tick_df[tick_df["ticket_category"] == "POST_DELIVERY"] if not tick_df.empty else tick_df
        
        prod_del = orders_universe.groupby(["brand", "canonical_product"]).size().reset_index(name="delivered")
        prod_tick = ticks_universe.groupby(["brand", "canonical_product"]).size().reset_index(name="tickets")
        
        df = prod_del.merge(prod_tick, on=["brand", "canonical_product"], how="outer").fillna(0)
        df["delivered"] = df["delivered"].astype(int)
        df["tickets"] = df["tickets"].astype(int)
        df["esc_pct"] = df.apply(lambda r: raw_esc(r["tickets"], r["delivered"]), axis=1)
        
    elif analysis_mode == "Pre Delivery":
        orders_universe = del_df
        ticks_universe = tick_df[tick_df["ticket_category"] == "PRE_DELIVERY"] if not tick_df.empty else tick_df
        
        prod_del = orders_universe.groupby(["brand", "canonical_product"]).size().reset_index(name="delivered")
        prod_tick = ticks_universe.groupby(["brand", "canonical_product"]).size().reset_index(name="tickets")
        
        df = prod_del.merge(prod_tick, on=["brand", "canonical_product"], how="outer").fillna(0)
        df["delivered"] = df["delivered"].astype(int)
        df["tickets"] = df["tickets"].astype(int)
        df["esc_pct"] = df.apply(lambda r: raw_esc(r["tickets"], r["delivered"]), axis=1)
        
    else:  # Combined Mode
        status_col = "order_status" if "order_status" in del_df.columns else None
        if status_col:
            del_orders = del_df[del_df[status_col].astype(str).str.strip().str.lower() == "delivered"]
        else:
            del_orders = del_df
        post_tix = tick_df[tick_df["ticket_category"] == "POST_DELIVERY"] if not tick_df.empty else tick_df
        all_orders = del_df
        pre_tix = tick_df[tick_df["ticket_category"] == "PRE_DELIVERY"] if not tick_df.empty else tick_df
        
        prod_del_post = del_orders.groupby(["brand", "canonical_product"]).size().reset_index(name="delivered_post")
        prod_tick_post = post_tix.groupby(["brand", "canonical_product"]).size().reset_index(name="tickets_post")
        
        prod_del_pre = all_orders.groupby(["brand", "canonical_product"]).size().reset_index(name="delivered_pre")
        prod_tick_pre = pre_tix.groupby(["brand", "canonical_product"]).size().reset_index(name="tickets_pre")
        
        df = prod_del_pre.merge(prod_del_post, on=["brand", "canonical_product"], how="outer").fillna(0)
        df = df.merge(prod_tick_pre, on=["brand", "canonical_product"], how="outer").fillna(0)
        df = df.merge(prod_tick_post, on=["brand", "canonical_product"], how="outer").fillna(0)
        
        df["delivered_pre"] = df["delivered_pre"].astype(int)
        df["delivered_post"] = df["delivered_post"].astype(int)
        df["tickets_pre"] = df["tickets_pre"].astype(int)
        df["tickets_post"] = df["tickets_post"].astype(int)
        
        df["pre_esc_pct"] = df.apply(lambda r: raw_esc(r["tickets_pre"], r["delivered_pre"]), axis=1)
        df["post_esc_pct"] = df.apply(lambda r: raw_esc(r["tickets_post"], r["delivered_post"]), axis=1)
        
        # Fallbacks
        df["delivered"] = df["delivered_pre"]
        df["tickets"] = df["tickets_pre"] + df["tickets_post"]
        df["esc_pct"] = df["post_esc_pct"]

    df["weighted_esc"] = df.apply(lambda r: weighted_esc(r["tickets"], r["delivered"]), axis=1)
    df["confidence"] = df["delivered"].apply(lambda d: round(confidence_factor(d) * 100))
    df["brand_product"] = df["brand"] + " | " + df["canonical_product"]
    
    primary_cohorts = {}
    ticket_aging = {}
    aging_cats = {}
    
    for (brand, prod), sub_ticks in tick_df.groupby(["brand", "canonical_product"]):
        if not sub_ticks.empty:
            primary_cohorts[(brand, prod)] = sub_ticks["Delivery Month"].value_counts().index[0]
            
            same_m, prev_m, older_m = 0, 0, 0
            for _, row in sub_ticks.iterrows():
                try:
                    diff_val = (row["Ticket Month Sort"] - row["Delivery Month Sort"])
                    if hasattr(diff_val, "n"):
                        diff = diff_val.n
                    else:
                        diff = int(diff_val)
                        
                    if diff <= 0:
                        same_m += 1
                    elif diff == 1:
                        prev_m += 1
                    else:
                        older_m += 1
                except:
                    same_m += 1
                    
            ticket_aging[(brand, prod)] = (same_m, prev_m, older_m)
            total = len(sub_ticks)
            if same_m / total >= 0.50:
                aging_cats[(brand, prod)] = "Emerging Risk"
            elif prev_m / total >= 0.50:
                aging_cats[(brand, prod)] = "Stable Risk"
            elif older_m / total >= 0.50:
                aging_cats[(brand, prod)] = "Historical Issue"
            else:
                aging_cats[(brand, prod)] = "Recovering"
        else:
            primary_cohorts[(brand, prod)] = "N/A"
            ticket_aging[(brand, prod)] = (0, 0, 0)
            aging_cats[(brand, prod)] = "Stable"
            
    df["Primary Ticket Source Month"] = df.apply(lambda r: primary_cohorts.get((r["brand"], r["canonical_product"]), "N/A"), axis=1)
    df["Same Month Tickets"] = df.apply(lambda r: ticket_aging.get((r["brand"], r["canonical_product"]), (0,0,0))[0], axis=1)
    df["Previous Month Tickets"] = df.apply(lambda r: ticket_aging.get((r["brand"], r["canonical_product"]), (0,0,0))[1], axis=1)
    df["Older Tickets"] = df.apply(lambda r: ticket_aging.get((r["brand"], r["canonical_product"]), (0,0,0))[2], axis=1)
    df["Ticket Aging Category"] = df.apply(lambda r: aging_cats.get((r["brand"], r["canonical_product"]), "Stable"), axis=1)
    
    df["impact"] = df.apply(
        lambda r: "CRITICAL" if r["delivered"] >= crit_del and r["esc_pct"] >= crit_esc and r["tickets"] >= crit_tix 
        else "HIGH" if r["delivered"] >= 200 and r["esc_pct"] >= high_esc
        else "MEDIUM" if r["delivered"] >= 100 and r["esc_pct"] >= 3.0
        else "LOW", axis=1
    )
    
    return df.sort_values("tickets", ascending=False).reset_index(drop=True)


def compute_cohort_report(del_df, tick_df):
    """Calculates chronological delivery cohort profiles using raw row counts."""
    if del_df.empty:
        return pd.DataFrame()
        
    cohort_del = del_df.groupby("Delivery Month Sort").size().reset_index(name="delivered")
    cohort_tick = tick_df.groupby("Delivery Month Sort").size().reset_index(name="tickets")
    
    df = cohort_del.merge(cohort_tick, on="Delivery Month Sort", how="outer").fillna(0)
    df["delivered"] = df["delivered"].astype(int)
    df["tickets"] = df["tickets"].astype(int)
    df["esc_pct"] = df.apply(lambda r: raw_esc(r["tickets"], r["delivered"]), axis=1)
    df["Delivery Month"] = df["Delivery Month Sort"].dt.strftime("%B %Y")
    
    return df.sort_values("Delivery Month Sort").reset_index(drop=True)


def compute_weekly_trends(del_df, tick_df, weeks_list):
    """Calculates weekly support trends and triggers spike alerts using raw row counts."""
    if del_df.empty:
        return pd.DataFrame()
        
    del_w = del_df.groupby("Delivery Week").size().reindex(weeks_list, fill_value=0)
    tick_w = tick_df.groupby("Delivery Week").size().reindex(weeks_list, fill_value=0)
    
    df = pd.DataFrame({
        "Week": weeks_list,
        "Delivered": del_w.values,
        "Tickets": tick_w.values
    })
    df["Esc %"] = df.apply(lambda r: raw_esc(r["Tickets"], r["Delivered"]), axis=1)
    df["WoW Change Tickets"] = df["Tickets"].diff().fillna(0).astype(int)
    df["WoW Change Esc %"] = df["Esc %"].diff().fillna(0.0).round(2)
    df["Spike Alert"] = df.apply(
        lambda r: "🚨 SPIKE" if r["Esc %"] >= 8.0 and r["Tickets"] >= 5 else "✅ STABLE", axis=1
    )
    return df


def compute_subcat_summary(tick_df):
    """Calculates overall subcategory ticket volume and share %."""
    if tick_df.empty:
        return pd.DataFrame()
    subcat_col = "subcat_final" if "subcat_final" in tick_df.columns else "raw_subcat"
    df = tick_df.groupby(subcat_col).size().reset_index(name="count")
    df = df.rename(columns={subcat_col: "subcat_final"})
    total = max(df["count"].sum(), 1)
    df["pct"] = (df["count"] / total * 100).round(1)
    df["tier"] = df["subcat_final"].apply(
        lambda s: "HIGH" if s in HIGH_SUBCATS else "MEDIUM" if s in MEDIUM_SUBCATS else "LOW"
    )
    return df.sort_values("count", ascending=False).reset_index(drop=True)


def top_kpis(brand_sum, prod_sum, subcat_sum, tick_df, del_df, weeks_list):
    """Aggregates high-level system metrics strictly using raw row count denominators."""
    total_del = len(del_df)
    total_tick = len(tick_df)
    overall = raw_esc(total_tick, total_del)
    
    subcat_col = "subcat_final" if "subcat_final" in tick_df.columns else "raw_subcat"
    defect_tix_count = len(tick_df[tick_df[subcat_col].isin(HIGH_SUBCATS)]) if not tick_df.empty else 0
    overall_defect = raw_esc(defect_tix_count, total_del)

    critical_n = len(brand_sum[brand_sum["impact"] == "CRITICAL"]) if not brand_sum.empty else 0
    high_n     = len(brand_sum[brand_sum["impact"] == "HIGH"]) if not brand_sum.empty else 0

    top_risk_brand = brand_sum.iloc[0]["brand"] if not brand_sum.empty else "—"
    top_risk_prod  = prod_sum.iloc[0]["canonical_product"][:40] if not prod_sum.empty else "—"
    top_issue      = subcat_sum.iloc[0]["subcat_final"] if not subcat_sum.empty else "—"

    spike_wk = "—"
    if not tick_df.empty and weeks_list:
        wk_totals = {wk: len(tick_df[tick_df["Delivery Week"] == wk]) for wk in weeks_list}
        if wk_totals:
            spike_wk = max(wk_totals, key=wk_totals.get)

    return {
        "total_del": total_del, "total_tick": total_tick, "overall_esc": overall,
        "overall_defect": overall_defect,
        "top_risk_brand": top_risk_brand, "top_risk_prod": top_risk_prod, "top_issue": top_issue,
        "spike_week": spike_wk,
        "critical_brands": critical_n, "high_brands": high_n,
        "n_brands": len(brand_sum),
    }
