import json

from .conftest import FakeLLM, load_sample, make_row


def post(client, rows, **params):
    return client.post("/api/v1/days", json=rows, params=params)


def test_ingest_sample_day_reports_the_bad_row(client):
    r = post(client, load_sample("2026-07-27"))
    body = r.json()
    assert r.status_code == 201 and body["accepted_count"] == 18 and body["rejected_count"] == 1
    assert body["rejected_rows"][0]["visit_id"] == "V-20260727-019" and body["rejected_rows"][0]["field"] == "payment_mode"
    assert body["warnings"][0]["type"] == "drug_name_merged"


def test_reupload_replaces_the_day_and_is_idempotent(client):
    post(client, load_sample("2026-07-27"))
    r = post(client, load_sample("2026-07-27"))
    assert r.status_code == 200 and r.json()["status"] == "replaced"
    assert client.get("/api/v1/days/2026-07-27/report").json()["visit_count"] == 18  # not doubled
    r2 = post(client, [make_row(clinic_id="CLN-KNP-014", timestamp="2026-07-27T10:00:00Z")])
    assert r2.json()["status"] == "replaced"
    assert client.get("/api/v1/days/2026-07-27/report").json()["visit_count"] == 1


def test_strict_mode_rejects_whole_file_and_stores_nothing(client):
    r = post(client, load_sample("2026-07-27"), strict="true")
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed"
    assert r.json()["error"]["details"][0]["visit_id"] == "V-20260727-019"
    assert client.get("/api/v1/days").json()["days"] == []


def test_all_rows_rejected_never_wipes_existing_day(client):
    post(client, load_sample("2026-07-27"))
    bad = [make_row(clinic_id="CLN-KNP-014", payment_mode="cheque")]
    r = post(client, bad, business_date="2026-07-27")
    assert r.status_code == 422 and r.json()["error"]["code"] == "all_rows_rejected"
    assert client.get("/api/v1/days/2026-07-27/report").json()["visit_count"] == 18


def test_empty_log_needs_a_date_but_is_valid_with_one(client):
    assert post(client, []).status_code == 422
    r = post(client, [], business_date="2026-07-26")
    assert r.status_code == 201
    assert client.get("/api/v1/days/2026-07-26/report").json()["totals"]["billed_paise"] == 0


def test_errors_are_structured_never_500(client):
    for body in ({"oops": 1}, "text", 42):
        r = client.post("/api/v1/days", json=body)
        assert r.status_code == 422 and "error" in r.json()
    r = client.post("/api/v1/days", content="{not json", headers={"content-type": "application/json"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"
    assert client.get("/api/v1/days/not-a-date/report").status_code == 422
    assert client.get("/api/v1/days/2030-01-01/report").json()["error"]["code"] == "day_not_found"


def test_report_shape_and_limit(seeded):
    r = seeded.get("/api/v1/days/2026-07-27/report", params={"limit": 2}).json()
    assert len(r["analytics"]["top_by_quantity"]) == 2 and r["clinic"]["name"].startswith("Mehta")
    assert r["data_quality"]["rejected_count"] == 1 and r["unavailable_metrics"][0]["metric"] == "profit"


def test_narrative_endpoint_fallback_then_cache_for_llm(make_client):
    good = json.dumps({"message": "{{total_billed}} billed. Profit isn't available without cost prices."})
    llm = FakeLLM(good, good)
    c = make_client(llm=llm, seed=True)
    first = c.get("/api/v1/days/2026-07-27/narrative").json()
    assert first["status"] == "success" and first["cached"] is False
    second = c.get("/api/v1/days/2026-07-27/narrative").json()
    assert second["cached"] is True and llm.calls == 1
    assert c.get("/api/v1/days/2026-07-27/narrative", params={"refresh": "true"}).json()["cached"] is False


def test_replacing_a_day_invalidates_its_narrative(make_client):
    good = json.dumps({"message": "{{total_billed}} billed. Profit is not available without cost prices."})
    c = make_client(llm=FakeLLM(good, good), seed=True)
    a = c.get("/api/v1/days/2026-07-27/narrative").json()
    post(c, [make_row(clinic_id="CLN-KNP-014")])
    b = c.get("/api/v1/days/2026-07-27/narrative").json()
    assert b["cached"] is False and b["report_hash"] != a["report_hash"]
    assert "\u20b940 billed" in b["message"]


def test_llm_outage_still_returns_a_narrative(make_client):
    from app.llm import LLMError
    c = make_client(llm=FakeLLM(LLMError("boom")), seed=True)
    r = c.get("/api/v1/days/2026-07-27/narrative")
    assert r.status_code == 200 and r.json()["status"] == "fallback"
