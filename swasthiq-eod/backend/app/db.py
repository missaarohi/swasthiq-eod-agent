"""SQLite storage. Plain sqlite3 so every query is visible and explainable.

Consistency rules:
  * Re-uploading a day REPLACES it inside one transaction (all-or-nothing).
  * Nothing derived (totals, rankings) is stored. Reports are recomputed from visit rows
    on every read, so they can never disagree with the stored data.
  * The narrative cache is keyed by a hash of the report and is deleted in the same
    transaction that replaces a day.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .validation import LineItem, Visit

SCHEMA = """
CREATE TABLE IF NOT EXISTS business_days (
  clinic_id TEXT NOT NULL,
  business_date TEXT NOT NULL,
  ingested_at TEXT NOT NULL,
  total_rows INTEGER NOT NULL,
  accepted_count INTEGER NOT NULL,
  rejected_count INTEGER NOT NULL,
  rejected_json TEXT NOT NULL,
  warnings_json TEXT NOT NULL,
  PRIMARY KEY (clinic_id, business_date)
);
CREATE TABLE IF NOT EXISTS visits (
  clinic_id TEXT NOT NULL,
  business_date TEXT NOT NULL,
  visit_id TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  doctor_id TEXT,
  line_items_json TEXT NOT NULL,
  payment_mode TEXT NOT NULL CHECK (payment_mode IN ('cash','card','upi')),
  amount_paid_paise INTEGER NOT NULL,
  discount_paise INTEGER NOT NULL CHECK (discount_paise >= 0),
  is_refund INTEGER NOT NULL CHECK (is_refund IN (0,1)),
  PRIMARY KEY (clinic_id, business_date, visit_id),
  FOREIGN KEY (clinic_id, business_date) REFERENCES business_days(clinic_id, business_date) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS narratives (
  clinic_id TEXT NOT NULL,
  business_date TEXT NOT NULL,
  report_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (clinic_id, business_date)
);
"""


class Database:
    def __init__(self, path):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        # one short-lived connection per operation; simple and thread-safe
        conn = sqlite3.connect(self.path, isolation_level=None)  # we manage transactions
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    # ---- writes ----

    def replace_day(self, clinic_id, business_date, visits, total_rows, errors, warnings):
        """Atomically replace one clinic-day. Returns 'created' or 'replaced'."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existed = conn.execute(
                    "SELECT 1 FROM business_days WHERE clinic_id=? AND business_date=?",
                    (clinic_id, business_date)).fetchone() is not None
                conn.execute("DELETE FROM narratives WHERE clinic_id=? AND business_date=?", (clinic_id, business_date))
                conn.execute("DELETE FROM visits WHERE clinic_id=? AND business_date=?", (clinic_id, business_date))
                conn.execute("DELETE FROM business_days WHERE clinic_id=? AND business_date=?", (clinic_id, business_date))
                conn.execute(
                    "INSERT INTO business_days VALUES (?,?,?,?,?,?,?,?)",
                    (clinic_id, business_date, now, total_rows, len(visits), len(errors),
                     json.dumps([e.to_dict() for e in errors]), json.dumps(warnings)))
                conn.executemany(
                    "INSERT INTO visits VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [(v.clinic_id, business_date, v.visit_id, v.timestamp.isoformat(), v.doctor_id,
                      json.dumps([[li.drug_name, li.qty, li.unit_price_paise] for li in v.line_items]),
                      v.payment_mode, v.amount_paid_paise, v.discount_paise, int(v.is_refund))
                     for v in visits])
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return "replaced" if existed else "created"

    def save_narrative(self, clinic_id, business_date, report_hash, payload):
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO narratives VALUES (?,?,?,?,?)",
                (clinic_id, business_date, report_hash, json.dumps(payload), datetime.now(timezone.utc).isoformat()))

    # ---- reads ----

    def list_days(self):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT clinic_id, business_date, accepted_count, rejected_count, ingested_at "
                "FROM business_days ORDER BY business_date DESC, clinic_id").fetchall()
        return [dict(r) for r in rows]

    def find_clinics_for_date(self, business_date):
        with self.connect() as conn:
            rows = conn.execute("SELECT clinic_id FROM business_days WHERE business_date=?", (business_date,)).fetchall()
        return [r["clinic_id"] for r in rows]

    def get_day(self, clinic_id, business_date):
        """Returns (meta dict, [Visit]) or None."""
        with self.connect() as conn:
            meta = conn.execute("SELECT * FROM business_days WHERE clinic_id=? AND business_date=?",
                                (clinic_id, business_date)).fetchone()
            if meta is None:
                return None
            rows = conn.execute("SELECT * FROM visits WHERE clinic_id=? AND business_date=? ORDER BY timestamp, visit_id",
                                (clinic_id, business_date)).fetchall()
        visits = [
            Visit(r["clinic_id"], r["visit_id"], datetime.fromisoformat(r["timestamp"]), r["doctor_id"],
                  tuple(LineItem(n, q, p) for n, q, p in json.loads(r["line_items_json"])),
                  r["payment_mode"], r["amount_paid_paise"], r["discount_paise"], bool(r["is_refund"]))
            for r in rows
        ]
        return dict(meta), visits

    def get_narrative(self, clinic_id, business_date):
        with self.connect() as conn:
            r = conn.execute("SELECT report_hash, payload_json FROM narratives WHERE clinic_id=? AND business_date=?",
                             (clinic_id, business_date)).fetchone()
        return (r["report_hash"], json.loads(r["payload_json"])) if r else None
