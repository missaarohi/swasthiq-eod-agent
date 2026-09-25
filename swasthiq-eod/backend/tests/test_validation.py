import pytest

from app.validation import BatchError, validate_batch, validate_record
from .conftest import load_sample, make_row


def fields(errors):
    return {e.field for e in errors}


def test_valid_row_becomes_visit():
    visit, errs = validate_record(make_row(), 1)
    assert errs == [] and visit.net_paise == 4000 and visit.payment_mode == "cash"


def test_missing_payment_mode_is_specific():
    row = make_row()
    del row["payment_mode"]
    visit, errs = validate_record(row, 7)
    assert visit is None
    assert errs[0].row == 7 and errs[0].field == "payment_mode" and "cash, card, upi" in errs[0].message
    assert errs[0].amount_paid_paise == 4000  # so the owner can see the money that is not reconciled


def test_all_problems_in_one_row_are_reported():
    _, errs = validate_record(make_row(payment_mode="cheque", amount_paid_paise=12.5, timestamp="yesterday"), 1)
    assert fields(errs) == {"payment_mode", "amount_paid_paise", "timestamp"}


@pytest.mark.parametrize("bad", [12.0, "4000", True, None])
def test_money_must_be_a_true_integer(bad):
    _, errs = validate_record(make_row(amount_paid_paise=bad), 1)
    assert "amount_paid_paise" in fields(errs)


def test_refund_sign_rules():
    assert "amount_paid_paise" in fields(validate_record(make_row(is_refund=True, amount_paid_paise=4000), 1)[1])
    assert "amount_paid_paise" in fields(validate_record(make_row(is_refund=False, amount_paid_paise=-4000), 1)[1])
    assert validate_record(make_row(is_refund=True, amount_paid_paise=-4000), 1)[1] == []


def test_discount_cannot_exceed_total():
    _, errs = validate_record(make_row(discount_paise=5000), 1)
    assert "discount_paise" in fields(errs)


def test_naive_timestamp_rejected():
    _, errs = validate_record(make_row(timestamp="2026-07-27T10:00:00"), 1)
    assert "timezone" in errs[0].message


def test_bad_line_items():
    _, errs = validate_record(make_row(line_items=[{"drug_name": "X", "qty": 0, "unit_price_paise": 10}]), 1)
    assert "line_items[0].qty" in fields(errs)
    assert "line_items" in fields(validate_record(make_row(line_items=[]), 1)[1])


def test_not_a_list_is_batch_error():
    with pytest.raises(BatchError):
        validate_batch({"a": 1})


def test_duplicate_visit_id_first_wins():
    res = validate_batch([make_row(), make_row(amount_paid_paise=1)])
    assert len(res.visits) == 1 and res.visits[0].amount_paid_paise == 4000
    assert res.errors[0].field == "visit_id" and res.errors[0].row == 2


def test_other_clinic_and_other_day_rows_rejected():
    res = validate_batch([make_row(), make_row(visit_id="V-2", clinic_id="OTHER"),
                          make_row(visit_id="V-3", timestamp="2026-07-28T10:00:00Z")], business_date="2026-07-27")
    assert [v.visit_id for v in res.visits] == ["V-1"]
    assert {e.field for e in res.errors} == {"clinic_id", "timestamp"}


def test_sample_day_27_edge_cases():
    res = validate_batch(load_sample("2026-07-27"))
    assert len(res.visits) == 18 and res.business_date == "2026-07-27"
    assert [e.visit_id for e in res.errors] == ["V-20260727-019"]
    # typo PARACETMOL merged into PARACETAMOL, and reported
    assert all(li.drug_name != "PARACETMOL" for v in res.visits for li in v.line_items)
    assert res.warnings[0]["type"] == "drug_name_merged"


def test_different_drugs_are_not_merged():
    rows = [make_row(visit_id=f"V-{i}", line_items=[{"drug_name": n, "qty": 1, "unit_price_paise": 100}], amount_paid_paise=100)
            for i, n in enumerate(["AMOXICILLIN", "OMEPRAZOLE", "METFORMIN"])]
    assert validate_batch(rows).warnings == []
