from app.reconcile import compute_report, hour_label
from app.validation import validate_batch
from .conftest import load_sample, make_row


def report_for(day):
    return compute_report(validate_batch(load_sample(day)).visits)


def test_day_27_totals_by_mode():
    r = report_for("2026-07-27")
    t = r["totals"]
    assert (t["billed_paise"], t["collected_paise"], t["outstanding_paise"], t["refunds_paise"]) == (319000, 317200, 1800, 0)
    assert t["gross_paise"] - t["discount_paise"] == t["billed_paise"]
    modes = {m["mode"]: m for m in r["by_payment_mode"]}
    assert (modes["cash"]["billed_paise"], modes["card"]["billed_paise"], modes["upi"]["billed_paise"]) == (127500, 83500, 108000)
    assert (modes["cash"]["outstanding_paise"], modes["card"]["outstanding_paise"], modes["upi"]["outstanding_paise"]) == (500, 800, 500)
    assert r["visit_count"] == 18 and r["pending_visit_count"] == 3 and r["collection_rate_pct"] == 99


def test_mode_splits_add_up_to_totals():
    r = report_for("2026-07-27")
    for key in ("billed_paise", "collected_paise", "outstanding_paise", "refunds_paise"):
        assert sum(m[key] for m in r["by_payment_mode"]) == r["totals"][key.replace("_paise", "_paise")]


def test_hour_buckets_sum_to_billed_and_peak():
    a = report_for("2026-07-27")["analytics"]
    assert sum(h["revenue_paise"] for h in a["revenue_by_hour"]) == 319000
    assert a["peak_hour"] == {"hour": 13, "label": "1pm\u20132pm", "revenue_paise": 76000}
    assert [h["hour"] for h in a["revenue_by_hour"]] == list(range(9, 19))  # gaps are kept as zero-hours


def test_two_distinct_rankings():
    a = report_for("2026-07-27")["analytics"]
    assert a["top_by_quantity"][0] == {"rank": 1, "drug_name": "OMEPRAZOLE", "qty": 18}
    assert a["top_by_revenue"][0] == {"rank": 1, "drug_name": "ATORVASTATIN", "revenue_paise": 120000}
    assert [d["drug_name"] for d in a["top_by_quantity"]] != [d["drug_name"] for d in a["top_by_revenue"]]
    # typo row counted under PARACETAMOL: 3+3+2+2+2+1
    assert {d["drug_name"]: d["qty"] for d in a["top_by_quantity"]}["PARACETAMOL"] == 13


def test_refund_only_day():
    r = report_for("2026-07-25")
    t = r["totals"]
    assert (t["billed_paise"], t["collected_paise"], t["refunds_paise"], t["net_collected_paise"]) == (0, 0, 49000, -49000)
    assert r["refund_count"] == 3 and r["collection_rate_pct"] is None
    modes = {m["mode"]: m["refunds_paise"] for m in r["by_payment_mode"]}
    assert modes == {"cash": 0, "card": 24000, "upi": 25000}
    assert r["analytics"]["peak_hour"] is None and r["analytics"]["top_by_quantity"] == []


def test_empty_day_is_all_zero_not_an_error():
    r = report_for("2026-07-26")
    assert r["totals"]["billed_paise"] == 0 and r["visit_count"] == 0 and r["analytics"]["revenue_by_hour"] == []


def test_overpayment_is_tracked_not_hidden():
    visits = validate_batch([make_row(amount_paid_paise=5000)]).visits
    r = compute_report(visits)
    assert r["totals"]["outstanding_paise"] == 0 and r["totals"]["overpaid_paise"] == 1000


def test_peak_hour_tie_goes_to_earlier_hour():
    rows = [make_row(visit_id="A", timestamp="2026-07-27T09:00:00Z"), make_row(visit_id="B", timestamp="2026-07-27T15:00:00Z")]
    assert compute_report(validate_batch(rows).visits)["analytics"]["peak_hour"]["hour"] == 9


def test_money_is_always_int():
    r = report_for("2026-07-27")
    assert all(isinstance(v, int) for v in r["totals"].values())


def test_hour_label():
    assert hour_label(0) == "12am\u20131am" and hour_label(11) == "11am\u201312pm" and hour_label(12) == "12pm\u20131pm"
