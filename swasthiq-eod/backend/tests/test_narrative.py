import json

from app.llm import LLMError
from app.narrative import build_figures, format_inr, generate_narrative
from .conftest import FakeLLM


def report(client, day="2026-07-27"):
    return client.app.state.service.report(day)


def ok(msg):
    return json.dumps({"message": msg})


GOOD = ("Good evening! {{total_billed}} billed across {{visit_count}} visits and {{total_collected}} collected. "
        "Busiest hour was {{peak_hour}}. We can't work out profit because cost price isn't in the data.")


def test_format_inr():
    assert format_inr(4285000) == "\u20b942,850" and format_inr(12345678) == "\u20b91,23,456.78" and format_inr(-49000) == "-\u20b9490"


def test_good_reply_is_rendered_with_exact_report_values(seeded):
    r = report(seeded)
    res = generate_narrative(r, FakeLLM(ok(GOOD)))
    assert res["status"] == "success" and res["source"] == "llm"
    assert "\u20b93,190 billed across 18 visits" in res["message"]
    keys = [f["key"] for f in res["traced_figures"]]
    assert keys == ["total_billed", "visit_count", "total_collected", "peak_hour"]
    figs = build_figures(r)
    assert all(f["display"] == figs[f["key"]].display for f in res["traced_figures"])


def test_number_typed_by_model_is_rejected_then_retry_succeeds(seeded):
    llm = FakeLLM(ok("We billed \u20b93,190 today. No profit data."), ok(GOOD))
    res = generate_narrative(report(seeded), llm)
    assert llm.calls == 2 and res["status"] == "success"


def test_number_words_and_unknown_keys_rejected(seeded):
    llm = FakeLLM(ok("Twelve visits today. No profit data."), ok("{{made_up}} today. No profit data."))
    res = generate_narrative(report(seeded), llm)
    assert res["status"] == "fallback" and "validation" in res["fallback_reason"]


def test_garbage_and_wrong_schema_fall_back_without_crashing(seeded):
    for bad in ["sorry, I can't", "```json\n{\"text\": \"hi\"}\n```", "[]", ""]:
        res = generate_narrative(report(seeded), FakeLLM(bad, bad))
        assert res["status"] == "fallback" and res["message"]


def test_fenced_json_is_accepted(seeded):
    res = generate_narrative(report(seeded), FakeLLM("```json\n" + ok(GOOD) + "\n```"))
    assert res["status"] == "success"


def test_profit_stated_as_fact_is_rejected(seeded):
    llm = FakeLLM(ok("Great profit today, {{total_billed}} billed."), ok("Great profit today."))
    assert generate_narrative(report(seeded), llm)["status"] == "fallback"


def test_missing_profit_sentence_is_added_and_flagged(seeded):
    res = generate_narrative(report(seeded), FakeLLM(ok("{{total_billed}} billed today.")))
    assert res["status"] == "success" and "not profit" in res["message"] and res["notes"]


def test_provider_error_falls_back_and_says_why(seeded):
    res = generate_narrative(report(seeded), FakeLLM(LLMError("HTTP 500")))
    assert res["status"] == "fallback" and "unavailable" in res["fallback_reason"]


def test_fallback_mentions_rejected_rows_and_profit(seeded):
    res = generate_narrative(report(seeded), None)
    assert "not included in these totals" in res["message"] and "not profit" in res["message"]


def test_every_number_in_fallback_traces_to_a_figure(seeded):
    import re
    for day in ("2026-07-25", "2026-07-26", "2026-07-27"):
        res = generate_narrative(report(seeded, day), None)
        text = res["message"]
        for f in res["traced_figures"]:
            text = text.replace(f["display"], " ")
        assert not re.search(r"\d", text), (day, text)
