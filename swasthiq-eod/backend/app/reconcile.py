"""Deterministic ground truth. This module NEVER calls an LLM and never uses floats for money.

Definitions (also documented in the README):
  billed       = sum over sale visits of (line items total - discount)
  collected    = sum over sale visits of amount_paid_paise
  outstanding  = sum over sale visits of max(0, billed - paid)   (per-visit shortfall)
  refunds      = sum over refund visits of |amount_paid_paise|
  revenue/hour = billed (after discount) of the sale visits in that hour
  drug revenue = qty * unit_price_paise (list price; discounts are per visit, not per drug)
Refund rows are kept out of billed, hour revenue and drug rankings; they only feed `refunds`.
"""
from collections import defaultdict

from . import config
from .validation import PAYMENT_MODES, local_time


def hour_label(h):
    def one(x):
        x %= 24
        suffix = "am" if x < 12 else "pm"
        return f"{x % 12 or 12}{suffix}"
    return f"{one(h)}\u2013{one(h + 1)}"


def _pct(numerator, denominator):
    """Integer percent, rounded half up, without floats. None when denominator is 0."""
    if denominator <= 0:
        return None
    return (numerator * 200 + denominator) // (2 * denominator)


def compute_report(visits, top_n=None):
    top_n = top_n or config.TOP_N
    modes = {
        m: {"mode": m, "billed_paise": 0, "collected_paise": 0, "outstanding_paise": 0,
            "refunds_paise": 0, "visit_count": 0, "pending_visit_count": 0, "refund_count": 0}
        for m in PAYMENT_MODES
    }
    hour_rev, hour_visits = defaultdict(int), defaultdict(int)
    drug_qty, drug_rev = defaultdict(int), defaultdict(int)
    gross_total = discount_total = overpaid = 0

    for v in visits:
        m = modes[v.payment_mode]
        if v.is_refund:
            m["refunds_paise"] += -v.amount_paid_paise
            m["refund_count"] += 1
            continue
        net = v.net_paise
        shortfall = max(0, net - v.amount_paid_paise)
        overpaid += max(0, v.amount_paid_paise - net)
        gross_total += v.gross_paise
        discount_total += v.discount_paise
        m["billed_paise"] += net
        m["collected_paise"] += v.amount_paid_paise
        m["outstanding_paise"] += shortfall
        m["visit_count"] += 1
        m["pending_visit_count"] += 1 if shortfall > 0 else 0
        h = local_time(v.timestamp).hour
        hour_rev[h] += net
        hour_visits[h] += 1
        for li in v.line_items:
            drug_qty[li.drug_name] += li.qty
            drug_rev[li.drug_name] += li.qty * li.unit_price_paise

    by_mode = [modes[m] for m in PAYMENT_MODES]
    billed = sum(m["billed_paise"] for m in by_mode)
    collected = sum(m["collected_paise"] for m in by_mode)
    refunds = sum(m["refunds_paise"] for m in by_mode)

    # revenue by hour: every hour between the first and last active hour (gaps show as 0)
    revenue_by_hour, peak = [], None
    if hour_rev:
        for h in range(min(hour_rev), max(hour_rev) + 1):
            revenue_by_hour.append({
                "hour": h, "label": hour_label(h),
                "revenue_paise": hour_rev.get(h, 0), "visit_count": hour_visits.get(h, 0),
            })
        ph = min(hour_rev, key=lambda h: (-hour_rev[h], h))  # ties -> earliest hour
        peak = {"hour": ph, "label": hour_label(ph), "revenue_paise": hour_rev[ph]}

    by_qty = sorted(drug_qty, key=lambda d: (-drug_qty[d], -drug_rev[d], d))[:top_n]
    by_rev = sorted(drug_rev, key=lambda d: (-drug_rev[d], -drug_qty[d], d))[:top_n]

    return {
        "visit_count": sum(m["visit_count"] for m in by_mode),
        "refund_count": sum(m["refund_count"] for m in by_mode),
        "pending_visit_count": sum(m["pending_visit_count"] for m in by_mode),
        "totals": {
            "gross_paise": gross_total,
            "discount_paise": discount_total,
            "billed_paise": billed,
            "collected_paise": collected,
            "outstanding_paise": sum(m["outstanding_paise"] for m in by_mode),
            "refunds_paise": refunds,
            "net_collected_paise": collected - refunds,
            "overpaid_paise": overpaid,
        },
        "collection_rate_pct": _pct(collected, billed),
        "by_payment_mode": by_mode,
        "analytics": {
            "revenue_by_hour": revenue_by_hour,
            "peak_hour": peak,
            "top_by_quantity": [{"rank": i + 1, "drug_name": d, "qty": drug_qty[d]} for i, d in enumerate(by_qty)],
            "top_by_revenue": [{"rank": i + 1, "drug_name": d, "revenue_paise": drug_rev[d]} for i, d in enumerate(by_rev)],
        },
        "unavailable_metrics": [
            {"metric": "profit", "reason": "Cost price is not part of the billing log, so profit cannot be computed."}
        ],
    }
