"""
engine_redistribute.py — Advanced Proportional Ticket Apportionment Engine (v4.0)
Calculates brand weights across categories safely with cap allocations.
"""
import numpy as np
import pandas as pd

HIGH_SUBCATS = ["Defective Product", "Damaged Product", "Low Quality Product", "Order Delay", "Order Not Shipped"]
MEDIUM_SUBCATS = ["Wrong Product Delivered", "Missing Items", "Refund Post Delivery", "Cancellation Request", "Tracking Query"]
LOW_SUBCATS = ["Colour Issue", "Size issue", "Quantity Mismatch", "Order Modification", "Address Change", "Payment Issue", "Order Confirmation Issue"]
ALL_REAL_SUBCATS = HIGH_SUBCATS + MEDIUM_SUBCATS + LOW_SUBCATS

MIN_ALLOC_PCT = 0.02
MAX_ALLOC_PCT = 0.35


def compute_brand_weights(brand_summary, valid_ticks):
    """Calculates weights: 40% Esc %, 30% Delivered, 20% Tickets, 10% WoW Trend [D]."""
    df = brand_summary.copy()
    if df.empty or df["delivered"].sum() == 0:
        return pd.Series(dtype=float)
        
    df = df[df["delivered"] > 0].copy()
    
    trend_sev = {}
    for brand in df["brand"]:
        b_tix = valid_ticks[valid_ticks["brand"] == brand]
        if len(b_tix) > 0 and "Ticket Week" in b_tix.columns:
            w_counts = b_tix.groupby("Ticket Week").size().sort_index()
            if len(w_counts) >= 2:
                trend_sev[brand] = max(0, w_counts.iloc[-1] - w_counts.iloc[-2])
            else:
                trend_sev[brand] = 0
        else:
            trend_sev[brand] = 0
            
    df["trend_severity"] = df["brand"].map(trend_sev).fillna(0)

    med_del = df["delivered"].median()
    med_esc = df["esc_pct"].median()
    
    eligible = df[(df["delivered"] >= max(100, med_del)) & (df["esc_pct"] >= max(1.5, med_esc))].copy()
    if len(eligible) < 2:
        eligible = df.nlargest(min(5, len(df)), "delivered").copy()

    esc_norm = eligible["esc_pct"] / max(eligible["esc_pct"].max(), 0.01)
    del_norm = eligible["delivered"] / max(eligible["delivered"].max(), 1)
    tick_norm = eligible["tickets"] / max(eligible["tickets"].max(), 1)
    trend_norm = eligible["trend_severity"] / max(eligible["trend_severity"].max(), 1)

    score = (0.40 * esc_norm) + (0.30 * del_norm) + (0.20 * tick_norm) + (0.10 * trend_norm)
    score = score.clip(lower=0.001)
    raw_pct = score / score.sum()
    
    weights = _apply_balancing_caps(raw_pct, MIN_ALLOC_PCT, MAX_ALLOC_PCT)
    return pd.Series(weights.values, index=eligible["brand"])


def _apply_balancing_caps(weights, min_pct, max_pct):
    w = weights.copy()
    for _ in range(30):
        changed = False
        over = w > max_pct
        under = w < min_pct
        if over.any():
            excess = (w[over] - max_pct).sum()
            w[over] = max_pct
            not_over = ~over
            if not_over.any():
                w[not_over] += excess * (w[not_over] / w[not_over].sum())
            changed = True
        if under.any():
            shortfall = (min_pct - w[under]).sum()
            w[under] = min_pct
            above = w > min_pct
            if above.any():
                sub = shortfall * (w[above] / w[above].sum())
                w[above] = (w[above] - sub).clip(lower=0)
            changed = True
        if not changed:
            break
    total = w.sum()
    return w / total if total > 0 else w


def redistribute_tickets(unmapped_df, brand_weights, rng):
    if len(unmapped_df) == 0 or len(brand_weights) == 0:
        return unmapped_df.copy()

    brands = brand_weights.index.tolist()
    probs = brand_weights.values.tolist()
    total = sum(probs)
    probs = [p / total for p in probs]

    result = unmapped_df.copy()
    assigned = rng.choice(brands, size=len(result), p=probs)
    result["brand"] = assigned
    result["_redistributed"] = True
    return result


def redistribute_subcat(raw_subcat, brand, product, ticket_category, rng):
    """Redistributes unmapped subcategories ensuring Pre/Post split integrity."""
    if raw_subcat not in ("Not Found", "Need Details"):
        return raw_subcat
        
    if str(ticket_category).upper() == "PRE_DELIVERY":
        cats = [
            "Order Delay", "Order Modification", "Cancellation Request", "Address Change",
            "Tracking Query", "Payment Issue", "Order Not Shipped", "Order Confirmation Issue"
        ]
        weights = {
            "Order Delay": 5.0,
            "Order Not Shipped": 4.0,
            "Tracking Query": 3.0,
            "Cancellation Request": 2.0,
            "Order Modification": 1.0,
            "Address Change": 1.0,
            "Payment Issue": 1.0,
            "Order Confirmation Issue": 1.0
        }
    else:
        cats = [
            "Defective Product", "Damaged Product", "Low Quality Product", "Size issue",
            "Wrong Product Delivered", "Missing Items", "Refund Post Delivery", "Colour Issue", "Quantity Mismatch"
        ]
        weights = {
            "Defective Product": 5.0,
            "Damaged Product": 4.0,
            "Low Quality Product": 3.0,
            "Size issue": 2.0,
            "Wrong Product Delivered": 0.8,
            "Missing Items": 0.8,
            "Refund Post Delivery": 0.8,
            "Colour Issue": 0.8,
            "Quantity Mismatch": 0.8
        }
        if not is_apparel_brand_or_product(brand, product):
            weights["Size issue"] = 0.0
            
    wts = [weights[c] for c in cats]
    total = sum(wts)
    probs = [w / total for w in wts]
    return rng.choice(cats, p=probs)


def is_apparel_brand_or_product(brand, product):
    brand_l = str(brand).lower()
    prod_l = str(product).lower()
    
    apparel_kws = {
        "wear", "clothing", "lifestyle", "apparel", "shirt", "tshirt", "jeans", "dress", 
        "fashion", "shoes", "socks", "bag", "glasses", "woggles", "beyoung", "sutra", 
        "campussutra", "hatke", "hirolas", "sneakare", "suit", "pant", "jacket", "hoodie",
        "sole", "sneaker", "ring", "watch", "pendant", "wallet", "belt", "cap", "hat", "tee"
    }
    tech_kws = {
        "tech", "clon", "geek", "verse", "zivx", "go5", "tecsox", "digimate", "clone", 
        "bluetooth", "wireless", "earphone", "headphone", "speaker", "charger", "cable", 
        "powerbank", "device", "smartwatch", "electronics"
    }
    
    if any(tk in brand_l or tk in prod_l for tk in tech_kws):
        return False
    return any(ak in brand_l or ak in prod_l for ak in apparel_kws)


def build_redistribution_summary(n_brand_nf, n_subcat_nf, n_need_details, brand_weights):
    """Builds a clear audit summary table of how unmapped files are distributed."""
    rows = []
    for brand, w in brand_weights.items():
        rows.append({
            "Brand": brand,
            "Weight": f"{w*100:.2f}%",
            "Brand NF Absorbed": round(n_brand_nf * w),
            "Subcat NF Absorbed": round(n_subcat_nf * w),
            "Need Details Absorbed": round(n_need_details * w),
        })
    return pd.DataFrame(rows)
