"""Row + batch validation for a raw billing log.

Rules of the design:
  * A bad row never causes a 500. It becomes a RowError that says which row, which
    field, and what to fix.
  * One row can have several problems; we report ALL of them, not just the first.
  * Money must be a real integer (no floats, no bools, no numeric strings).
"""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import re

from . import config

PAYMENT_MODES = ("cash", "card", "upi")


class BatchError(Exception):
    """The whole payload is unusable (not a list, etc.)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class LineItem:
    drug_name: str
    qty: int
    unit_price_paise: int


@dataclass(frozen=True)
class Visit:
    clinic_id: str
    visit_id: str
    timestamp: datetime  # always timezone-aware UTC
    doctor_id: str | None
    line_items: tuple
    payment_mode: str
    amount_paid_paise: int
    discount_paise: int
    is_refund: bool

    @property
    def gross_paise(self):
        return sum(li.qty * li.unit_price_paise for li in self.line_items)

    @property
    def net_paise(self):
        """What the patient was actually billed: list price minus visit discount."""
        return self.gross_paise - self.discount_paise


@dataclass
class RowError:
    row: int  # 1-based position in the uploaded array
    visit_id: str | None
    field: str
    message: str
    amount_paid_paise: int | None = None  # money on the rejected row, if readable

    def to_dict(self):
        return {
            "row": self.row,
            "visit_id": self.visit_id,
            "field": self.field,
            "message": self.message,
            "amount_paid_paise": self.amount_paid_paise,
        }


@dataclass
class BatchResult:
    clinic_id: str | None
    business_date: str | None
    visits: list
    errors: list
    warnings: list
    total_rows: int


# ---------- small helpers ----------

def _is_int(v):
    # bool is a subclass of int in Python, so exclude it explicitly
    return isinstance(v, int) and not isinstance(v, bool)


def _type_name(v):
    return "null" if v is None else type(v).__name__


def normalize_drug_name(name):
    return re.sub(r"\s+", " ", name).strip().upper()


def local_time(ts):
    """Timestamp shifted by the configured bucketing offset (default: UTC)."""
    return ts + timedelta(minutes=config.HOUR_BUCKET_OFFSET_MINUTES)


def business_date_of(ts):
    return local_time(ts).date().isoformat()


def parse_timestamp(value):
    """Return an aware UTC datetime or raise ValueError with a fix-it message."""
    if not isinstance(value, str):
        raise ValueError(f"must be an ISO 8601 string like 2026-07-27T09:10:00Z, got {_type_name(value)}")
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"'{value}' is not valid ISO 8601 (example: 2026-07-27T09:10:00Z)")
    if dt.tzinfo is None:
        raise ValueError(f"'{value}' has no timezone; add a UTC marker like 'Z'")
    return dt.astimezone(timezone.utc)


# ---------- single row ----------

def validate_record(raw, row):
    """Validate one raw row. Returns (Visit | None, [RowError])."""
    if not isinstance(raw, dict):
        return None, [RowError(row, None, "(row)", f"Row must be a JSON object, got {_type_name(raw)}.")]

    errors = []
    vid = raw.get("visit_id")
    vid_label = vid.strip() if isinstance(vid, str) and vid.strip() else None
    amt = raw.get("amount_paid_paise")
    amt_ctx = amt if _is_int(amt) else None

    def err(field, msg):
        errors.append(RowError(row, vid_label, field, msg, amt_ctx))

    def req_str(field):
        v = raw.get(field)
        if v is None:
            err(field, f"Missing required field '{field}'.")
        elif not isinstance(v, str) or not v.strip():
            err(field, f"'{field}' must be a non-empty string, got {_type_name(v)}.")
        else:
            return v.strip()
        return None

    def req_int(field, minimum):
        v = raw.get(field)
        if v is None:
            err(field, f"Missing required field '{field}' (integer paise).")
        elif not _is_int(v):
            err(field, f"'{field}' must be an integer number of paise, got {_type_name(v)} ({v!r}). Do not send rupees or decimals.")
        elif minimum is not None and v < minimum:
            err(field, f"'{field}' must be >= {minimum}, got {v}.")
        else:
            return v
        return None

    clinic_id = req_str("clinic_id")
    visit_id = req_str("visit_id")
    doctor_id = raw.get("doctor_id")
    if doctor_id is not None and not isinstance(doctor_id, str):
        err("doctor_id", f"'doctor_id' must be a string when present, got {_type_name(doctor_id)}.")
        doctor_id = None

    ts = None
    if raw.get("timestamp") is None:
        err("timestamp", "Missing required field 'timestamp'.")
    else:
        try:
            ts = parse_timestamp(raw["timestamp"])
        except ValueError as e:
            err("timestamp", f"'timestamp' {e}.")

    mode = raw.get("payment_mode")
    if mode is None:
        err("payment_mode", "Missing required field 'payment_mode'. Expected one of: cash, card, upi.")
        mode = None
    elif not isinstance(mode, str) or mode.strip().lower() not in PAYMENT_MODES:
        err("payment_mode", f"'payment_mode' must be one of cash, card, upi; got {mode!r}.")
        mode = None
    else:
        mode = mode.strip().lower()

    is_refund = raw.get("is_refund")
    if is_refund is None:
        err("is_refund", "Missing required field 'is_refund' (true/false).")
    elif not isinstance(is_refund, bool):
        err("is_refund", f"'is_refund' must be true or false, got {_type_name(is_refund)} ({is_refund!r}).")
        is_refund = None

    discount = req_int("discount_paise", 0)
    # amount sign depends on is_refund, so only check "is an int" here
    paid = req_int("amount_paid_paise", None)

    items = []
    li_raw = raw.get("line_items")
    if li_raw is None:
        err("line_items", "Missing required field 'line_items'.")
    elif not isinstance(li_raw, list) or not li_raw:
        err("line_items", "'line_items' must be a non-empty array of {drug_name, qty, unit_price_paise}.")
    else:
        for i, li in enumerate(li_raw):
            p = f"line_items[{i}]"
            if not isinstance(li, dict):
                err(p, f"{p} must be an object, got {_type_name(li)}.")
                continue
            name, qty, price = li.get("drug_name"), li.get("qty"), li.get("unit_price_paise")
            ok = True
            if not isinstance(name, str) or not name.strip():
                err(f"{p}.drug_name", f"{p}.drug_name must be a non-empty string."); ok = False
            if not _is_int(qty) or qty <= 0:
                err(f"{p}.qty", f"{p}.qty must be a positive integer, got {qty!r}."); ok = False
            if not _is_int(price) or price < 0:
                err(f"{p}.unit_price_paise", f"{p}.unit_price_paise must be a non-negative integer (paise), got {price!r}."); ok = False
            if ok:
                items.append(LineItem(normalize_drug_name(name), qty, price))

    # cross-field checks: only when the fields involved are themselves valid
    if paid is not None and is_refund is not None:
        if is_refund and paid >= 0:
            err("amount_paid_paise", f"Refund rows must have a negative amount_paid_paise, got {paid}.")
            paid = None
        elif not is_refund and paid < 0:
            err("amount_paid_paise", f"Non-refund rows cannot have a negative amount_paid_paise ({paid}). Set is_refund=true if this is a refund.")
            paid = None
    if items and li_raw and len(items) == len(li_raw) and discount is not None:
        gross = sum(li.qty * li.unit_price_paise for li in items)
        if discount > gross:
            err("discount_paise", f"discount_paise ({discount}) is more than the line items total ({gross}).")

    if errors:
        return None, errors
    return Visit(clinic_id, visit_id, ts, doctor_id, tuple(items), mode, paid, discount, is_refund), []


# ---------- whole file ----------

def _canonicalize_drugs(visits):
    """Merge near-duplicate drug spellings (e.g. PARACETMOL -> PARACETAMOL).

    The most frequent spelling wins. Every merge is reported as a warning so the owner
    can see it; nothing is changed silently.
    """
    counts = Counter(li.drug_name for v in visits for li in v.line_items)
    ordered = sorted(counts, key=lambda n: (-counts[n], n))
    canonical, mapping = [], {}
    for name in ordered:
        match = next(
            (c for c in canonical if SequenceMatcher(None, name, c).ratio() >= config.DRUG_FUZZY_THRESHOLD),
            None,
        )
        if match:
            mapping[name] = match
        else:
            canonical.append(name)
    if not mapping:
        return visits, []

    warnings, out = [], []
    for v in visits:
        new_items = []
        for li in v.line_items:
            target = mapping.get(li.drug_name)
            if target:
                warnings.append({
                    "type": "drug_name_merged",
                    "visit_id": v.visit_id,
                    "message": f"Drug name '{li.drug_name}' looks like a typo of '{target}' and was counted as '{target}'.",
                })
                li = LineItem(target, li.qty, li.unit_price_paise)
            new_items.append(li)
        out.append(Visit(v.clinic_id, v.visit_id, v.timestamp, v.doctor_id, tuple(new_items),
                         v.payment_mode, v.amount_paid_paise, v.discount_paise, v.is_refund))
    return out, warnings


def validate_batch(records, business_date=None, clinic_id=None):
    if not isinstance(records, list):
        raise BatchError("invalid_payload", "Records must be a JSON array of visit objects.")

    errors, parsed = [], []  # parsed: (row, Visit)
    for i, raw in enumerate(records, start=1):
        visit, errs = validate_record(raw, i)
        errors.extend(errs)
        if visit:
            parsed.append((i, visit))

    # single clinic per file: majority wins unless the caller named one
    if parsed:
        target_clinic = clinic_id or Counter(v.clinic_id for _, v in parsed).most_common(1)[0][0]
    else:
        target_clinic = clinic_id
    kept = []
    for row, v in parsed:
        if v.clinic_id != target_clinic:
            errors.append(RowError(row, v.visit_id, "clinic_id",
                                   f"Row is for clinic '{v.clinic_id}' but this log is for '{target_clinic}'. One clinic per log.",
                                   v.amount_paid_paise))
        else:
            kept.append((row, v))

    # single day per file
    target_date = business_date
    if target_date is None and kept:
        target_date = Counter(business_date_of(v.timestamp) for _, v in kept).most_common(1)[0][0]
    parsed, kept = kept, []
    for row, v in parsed:
        d = business_date_of(v.timestamp)
        if d != target_date:
            errors.append(RowError(row, v.visit_id, "timestamp",
                                   f"Timestamp falls on {d} but this log is for {target_date}. One day per log.",
                                   v.amount_paid_paise))
        else:
            kept.append((row, v))

    # visit_id must be unique: first occurrence wins
    seen, unique = set(), []
    for row, v in kept:
        if v.visit_id in seen:
            errors.append(RowError(row, v.visit_id, "visit_id",
                                   f"Duplicate visit_id '{v.visit_id}'; the first occurrence was kept.",
                                   v.amount_paid_paise))
        else:
            seen.add(v.visit_id)
            unique.append(v)

    visits, warnings = _canonicalize_drugs(unique)
    errors.sort(key=lambda e: e.row)
    return BatchResult(target_clinic, target_date, visits, errors, warnings, len(records))
