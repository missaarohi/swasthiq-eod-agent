"""Narrative layer: the LLM writes words, the server supplies every number.

How grounding works (three locks):
  1. The model is given a menu of figures and may only refer to them as {{key}}
     placeholders. It never types a number.
  2. Its reply is parsed as strict JSON and checked: known keys only, no digits or number
     words left in the text, profit is only mentioned as "not available".
  3. The server substitutes the exact display strings from the deterministic report and
     returns a `traced_figures` list (display value + report field) as proof.
If the model fails any check twice, or is unavailable, a deterministic template is used
and the response says so (status = "fallback").
"""
import json
import re
from dataclasses import dataclass
from datetime import date

from .llm import LLMError

PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
NUMBER_WORDS = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|hundred|thousand|lakh|crore|dozen)\b", re.I)
NEGATION = re.compile(r"\b(cannot|can not|not|unavailable|without|missing|no cost)\b|n['\u2019]t\b", re.I)
PROFIT_NOTE = "Note: cost data isn't available, so this is revenue, not profit \u2014 flagging rather than estimating."


class NarrativeRejected(Exception):
    """The model's reply failed one of our checks."""


@dataclass(frozen=True)
class Figure:
    key: str
    display: str
    report_field: str


# ---------- formatting ----------

def format_inr(paise):
    sign = "-" if paise < 0 else ""
    paise = abs(paise)
    rupees, rem = divmod(paise, 100)
    s = str(rupees)
    if len(s) > 3:  # Indian grouping: 12,34,567
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return f"{sign}\u20b9{s}" + (f".{rem:02d}" if rem else "")


def format_date(iso):
    return date.fromisoformat(iso).strftime("%d %b %Y").lstrip("0")


# ---------- figure menu ----------

def build_figures(report):
    t, a, f = report["totals"], report["analytics"], {}

    def add(key, display, field):
        f[key] = Figure(key, str(display), field)

    add("date", format_date(report["business_date"]), "business_date")
    add("total_billed", format_inr(t["billed_paise"]), "totals.billed_paise")
    add("total_collected", format_inr(t["collected_paise"]), "totals.collected_paise")
    add("outstanding", format_inr(t["outstanding_paise"]), "totals.outstanding_paise")
    add("refunds", format_inr(t["refunds_paise"]), "totals.refunds_paise")
    add("visit_count", report["visit_count"], "visit_count")
    add("pending_visits", report["pending_visit_count"], "pending_visit_count")
    add("refund_count", report["refund_count"], "refund_count")
    if report["collection_rate_pct"] is not None:
        add("collection_rate", f"{report['collection_rate_pct']}%", "collection_rate_pct")
    if a["peak_hour"]:
        add("peak_hour", a["peak_hour"]["label"], "analytics.peak_hour.label")
        add("peak_hour_revenue", format_inr(a["peak_hour"]["revenue_paise"]), "analytics.peak_hour.revenue_paise")
    if a["top_by_quantity"]:
        add("top_qty_drug", a["top_by_quantity"][0]["drug_name"], "analytics.top_by_quantity[0].drug_name")
        add("top_qty_units", a["top_by_quantity"][0]["qty"], "analytics.top_by_quantity[0].qty")
    if a["top_by_revenue"]:
        add("top_revenue_drug", a["top_by_revenue"][0]["drug_name"], "analytics.top_by_revenue[0].drug_name")
        add("top_revenue_amount", format_inr(a["top_by_revenue"][0]["revenue_paise"]), "analytics.top_by_revenue[0].revenue_paise")
    if report["data_quality"]["rejected_count"]:
        add("rejected_rows", report["data_quality"]["rejected_count"], "data_quality.rejected_count")
    return f


# ---------- prompt ----------

SYSTEM_PROMPT = """You write end-of-day WhatsApp summaries for an Indian clinic owner.

Hard rules:
1. You get a list of FIGURES, each with a key. Refer to a figure ONLY as a {{key}} placeholder, for example {{total_billed}}. The system swaps in the exact value.
2. NEVER type a digit or a number word (two, twelve, hundred...) yourself. No amounts, counts, dates or percentages except through placeholders.
3. Use only keys from the list. Do not invent keys. Skip anything not listed.
4. Profit cannot be computed because cost price is not in the data. Say that plainly in one sentence. Never estimate profit or call revenue profit.
5. If rejected_rows is listed, tell the owner those rows are not included in the totals.
6. Tone: warm, brief, plain English, WhatsApp style, about 80 words at most. State only what the figures show; no comparisons with other days.

Reply with ONLY this JSON and nothing else: {"message": "<the WhatsApp text>"}"""


def safe_clinic_name(report):
    """Clinic name as literal text. Names containing digits (e.g. a raw clinic id) are avoided
    because digits are not allowed in the literal text of a narrative."""
    name = report["clinic"]["name"]
    return "your clinic" if re.search(r"\d", name) else name


def build_user_prompt(report, figures, previous_error=None):
    clinic = safe_clinic_name(report)
    lines = [f"Clinic: {clinic}", "FIGURES (key: value the owner will see):"]
    lines += [f"- {fig.key}: {fig.display}" for fig in figures.values()]
    if previous_error:
        lines.append(f"\nYour previous reply was rejected: {previous_error}. Fix that and reply with the JSON only.")
    return "\n".join(lines)


# ---------- verification + rendering ----------

def _extract_json(raw):
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise NarrativeRejected("reply was not a JSON object")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        raise NarrativeRejected("reply was not valid JSON")
    if not isinstance(data, dict) or not isinstance(data.get("message"), str) or not data["message"].strip():
        raise NarrativeRejected("JSON must be an object with a non-empty string field 'message'")
    if len(data["message"]) > 1200:
        raise NarrativeRejected("message is too long for a WhatsApp summary")
    return data["message"].strip()


def verify_and_render(message, figures):
    used = PLACEHOLDER.findall(message)
    unknown = sorted({k for k in used if k not in figures})
    if unknown:
        raise NarrativeRejected(f"unknown placeholder(s): {', '.join(unknown)}")
    literal = PLACEHOLDER.sub(" ", message)
    if "{{" in literal or "}}" in literal:
        raise NarrativeRejected("malformed placeholder")
    if re.search(r"\d", literal):
        raise NarrativeRejected("message contains a number typed by the model; numbers must be placeholders")
    if NUMBER_WORDS.search(literal):
        raise NarrativeRejected("message contains a number written as a word")
    notes = []
    for sentence in re.split(r"[.!?\n]+", literal):
        if re.search(r"\bprofit", sentence, re.I) and not NEGATION.search(sentence):
            raise NarrativeRejected("message talks about profit as if it were known")
    if not re.search(r"\bprofit", literal, re.I):
        message = message.rstrip() + "\n\n" + PROFIT_NOTE
        notes.append("Profit limitation sentence was added because the model left it out.")

    segments, cursor, traced = [], 0, {}
    for m in PLACEHOLDER.finditer(message):
        if m.start() > cursor:
            segments.append({"text": message[cursor:m.start()]})
        fig = figures[m.group(1)]
        segments.append({"text": fig.display, "key": fig.key})
        traced.setdefault(fig.key, {"key": fig.key, "display": fig.display, "report_field": fig.report_field})
        cursor = m.end()
    if cursor < len(message):
        segments.append({"text": message[cursor:]})
    return {
        "message": "".join(s["text"] for s in segments),
        "segments": segments,
        "traced_figures": list(traced.values()),
        "notes": notes,
    }


# ---------- deterministic fallback ----------

def _plural(n, word):
    return word if n == 1 else word + "s"


def template_message(report):
    t = report["totals"]
    vc, pv, rc = report["visit_count"], report["pending_visit_count"], report["refund_count"]
    a = report["analytics"]
    out = [f"Good evening! Here's the summary for {safe_clinic_name(report)} ({{{{date}}}}):"]

    if vc == 0:
        body = ["No sales were logged for this day."]
    else:
        body = [f"{{{{total_billed}}}} billed across {{{{visit_count}}}} {_plural(vc, 'visit')}, "
                + ("{{total_collected}} collected ({{collection_rate}})." if report["collection_rate_pct"] is not None
                   else "{{total_collected}} collected.")]
        body.append(f"{{{{outstanding}}}} is still outstanding across {{{{pending_visits}}}} {_plural(pv, 'visit')}."
                    if t["outstanding_paise"] > 0 else "Nothing is outstanding.")
    body.append("{{refunds}} was refunded across {{refund_count}} " + _plural(rc, "refund") + "."
                if rc else "No refunds were logged.")
    out.append(" ".join(body))

    if a["peak_hour"]:
        out.append("Busiest hour: {{peak_hour}}, with {{peak_hour_revenue}} in revenue.")
    if a["top_by_quantity"]:
        out.append("Top mover by quantity: {{top_qty_drug}} ({{top_qty_units}} units).\n"
                   "Top by revenue: {{top_revenue_drug}} ({{top_revenue_amount}}).")
    rej = report["data_quality"]["rejected_count"]
    if rej:
        out.append("Heads up: {{rejected_rows}} " + _plural(rej, "row") + " in the log could not be processed and "
                   + ("is" if rej == 1 else "are") + " not included in these totals.")
    out.append(PROFIT_NOTE)
    return "\n\n".join(out)


# ---------- entry point ----------

def generate_narrative(report, llm, max_attempts=2):
    figures = build_figures(report)
    reason, last_error = None, None

    if llm is None:
        reason = "No LLM API key is configured."
    else:
        for _ in range(max_attempts):
            try:
                raw = llm.complete(SYSTEM_PROMPT, build_user_prompt(report, figures, last_error))
                rendered = verify_and_render(_extract_json(raw), figures)
                return {**rendered, "status": "success", "source": "llm", "model": llm.model, "fallback_reason": None}
            except NarrativeRejected as e:
                last_error = str(e)
                reason = f"The model's reply failed validation: {last_error}."
            except LLMError as e:
                reason = f"The LLM was unavailable: {e}."
                break  # provider is down; retrying immediately rarely helps

    rendered = verify_and_render(template_message(report), figures)
    return {**rendered, "status": "fallback", "source": "template", "model": None, "fallback_reason": reason}
