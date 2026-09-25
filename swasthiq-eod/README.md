# EOD Billing & Analytics Agent

**Live app:** https://swasthiq-eod-frontend.vercel.app
**Backend API:** https://swasthiq-eod-agent-ekcg.onrender.com
**Repo:** https://github.com/missaarohi/swasthiq-eod-agent

A Python REST API that turns a clinic's daily billing log into (1) a deterministic end-of-day
reconciliation, (2) analytics, and (3) a short WhatsApp-style narrative written by a language model
and checked against the numbers. A React app presents the three screens.

```
backend/    FastAPI + SQLite. app/ (code), tests/ (pytest), sample_data/ (the 3 provided days)
frontend/   React + Vite. Three screens with a shared sidebar
```

## Run locally

```bash
# backend  (http://localhost:8000, docs at /docs)
cd backend
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...     # optional; without it the narrative uses a fixed template
uvicorn app.main:app --reload
python -m pytest -q                     # 47 tests

# frontend (http://localhost:5173; /api is proxied to :8000)
cd frontend
npm install && npm run dev
```

On first start the three sample days are loaded automatically (`SEED_SAMPLE_DATA=0` turns this off).

| Env var | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | empty | Enables the LLM narrative. Empty = deterministic template, clearly labelled |
| `LLM_MODEL` | `claude-haiku-4-5-20251001` | Model used for the narrative |
| `DB_PATH` | `backend/data/eod.db` | SQLite file |
| `HOUR_BUCKET_OFFSET_MINUTES` | `0` | Hour-of-day bucketing offset. `0` = UTC (as the brief says); `330` = IST |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `VITE_API_BASE_URL` (frontend) | empty | Deployed backend URL |

## Definitions (all money is integer paise; floats are never used)

| Term | Definition |
|---|---|
| billed | sum over sale visits of `sum(qty * unit_price_paise) - discount_paise` |
| collected | sum over sale visits of `amount_paid_paise` |
| outstanding | sum over sale visits of `max(0, billed - paid)` (per-visit shortfall) |
| refunds | sum over refund visits of `abs(amount_paid_paise)` |
| revenue by hour | billed value (after discount) of sale visits in that hour |
| drug revenue | `qty * unit_price_paise` (list price; discounts are per visit, so not split across drugs) |
| overpaid | `max(0, paid - billed)`, reported separately, never netted against outstanding |

Refund rows are excluded from billed, hourly revenue and drug rankings; they only feed `refunds`.
Every split by payment mode sums exactly to the total (asserted in tests).
Ties: peak hour goes to the earlier hour; rankings break ties by the other metric, then by name.

## API contract

Errors always look like `{"error": {"code": "...", "message": "...", "details": [...]}}`.

### `POST /api/v1/days` — ingest (or replace) one clinic-day
Body: a bare JSON array of visit records, or `{"records": [...], "business_date": "YYYY-MM-DD", "clinic_id": "..."}`.
Query: `strict=true` rejects the whole file if any row is bad and stores nothing.
`business_date` is inferred from the rows; it is required only for an empty log.

`201` (new day) / `200` (day replaced):
```json
{ "status": "created", "clinic_id": "CLN-KNP-014", "business_date": "2026-07-27",
  "total_rows": 19, "accepted_count": 18, "rejected_count": 1,
  "rejected_rows": [{"row": 19, "visit_id": "V-20260727-019", "field": "payment_mode",
                     "message": "Missing required field 'payment_mode'. Expected one of: cash, card, upi.",
                     "amount_paid_paise": 4000}],
  "warnings": [{"type": "drug_name_merged", "visit_id": "V-20260727-009", "message": "..."}] }
```
`422` codes: `invalid_payload`, `invalid_business_date`, `business_date_required`,
`validation_failed` (strict), `all_rows_rejected` (nothing valid; existing data untouched), `invalid_request`.

### `GET /api/v1/days` — list ingested days
`{"days": [{"clinic_id", "business_date", "accepted_count", "rejected_count", "ingested_at"}]}`

### `GET /api/v1/days/{date}/report?clinic_id=&limit=5` — reconciliation + analytics
```
visit_count, refund_count, pending_visit_count, collection_rate_pct (int | null)
totals: gross, discount, billed, collected, outstanding, refunds, net_collected, overpaid   (all *_paise)
by_payment_mode: [{mode, billed_paise, collected_paise, outstanding_paise, refunds_paise, visit_count, ...}]  cash, card, upi
analytics: revenue_by_hour [{hour, label, revenue_paise, visit_count}], peak_hour | null,
           top_by_quantity [{rank, drug_name, qty}], top_by_revenue [{rank, drug_name, revenue_paise}]
data_quality: {total_rows, accepted_count, rejected_count, rejected_rows[], warnings[]}
unavailable_metrics: [{metric: "profit", reason}]
```
`404 day_not_found`, `400 clinic_id_required` (several clinics on one date).

### `GET /api/v1/days/{date}/narrative?refresh=false`
```
status: "success" | "fallback",  source: "llm" | "template",  fallback_reason,
message,  segments [{text, key?}],  traced_figures [{key, display, report_field}],  notes[],  cached
```
`fallback` means the model was unavailable or failed validation, and a fixed template was used instead.

## Edge cases in the sample data

| Case | Handling |
|---|---|
| 26 Jul is an empty file `[]` | Valid day: all zeros, no peak hour, empty rankings, narrative says no sales |
| 25 Jul has only refunds | billed 0, refunds 49000 paise, net collected negative; no analytics |
| `V-20260727-019` has no `payment_mode` | Row rejected with row number, field and fix; reported with its ₹ amount so the owner sees what is unreconciled |
| `PARACETMOL` typo | Merged into `PARACETAMOL` (similarity >= 0.9 to a more frequent spelling) and reported as a warning |
| Rows out of time order / same timestamp | Order never matters; everything is bucketed and summed |
| Partial payments (visits 004, 011, 016) | Counted as outstanding per visit: 500 + 500 + 800 paise, 3 pending visits |
| Discounts | Billed is after discount; total discount is reported |

Also rejected: floats or numeric strings for money, non-boolean `is_refund`, refund with a non-negative
amount, sale with a negative amount, discount above the line total, naive timestamps (no timezone),
`qty <= 0`, empty `line_items`, duplicate `visit_id` (first kept), rows from another clinic or another day.
All problems in a row are listed together.

## How data stays consistent on update

1. **Replace, don't merge.** Re-posting a day runs one `BEGIN IMMEDIATE` transaction that deletes the old
   day (visits, metadata, cached narrative) and inserts the new one. Readers see the old day or the new day, never a mix.
   Posting the same file twice gives the same result (idempotent).
2. **A bad upload cannot wipe good data.** If nothing valid is found (`all_rows_rejected`), or strict mode fails,
   the transaction is never started.
3. **Nothing derived is stored.** Totals and rankings are recomputed from visit rows on every read, so
   they cannot drift from the data.
4. **The narrative cache is keyed by a hash of the report.** A changed report has a different hash, so a stale
   narrative is never served. Fallback narratives are not cached.
5. **Database guards.** Primary keys `(clinic_id, business_date, visit_id)`, `CHECK` constraints on payment mode and discount,
   foreign keys with cascade.

## How the narrative stays grounded

1. The model gets a menu of figures (`total_billed: ₹3,190`, ...) and may only write `{{total_billed}}`-style
   placeholders. It never types a number.
2. Its reply must be strict JSON `{"message": "..."}`. It is rejected if a placeholder is unknown, if any digit or
   number-word is left in the text, or if it talks about profit as if it were known.
3. The server substitutes the exact display strings from the report and returns `traced_figures`, each pointing to
   the report field it came from (shown in the UI panel).
4. One retry with the rejection reason. Then the deterministic template is used and labelled `fallback`.
5. If the model omits the "profit can't be computed" sentence, the server appends it and says so in `notes`.

Limitation: the checks guarantee every number is real, not that every word is wise. The prompt forbids comparisons
and trends, but the code cannot verify qualitative claims.

## Testing

`python -m pytest -q` runs 47 tests: validation (each rule), reconciliation on all three sample days,
narrative checks with a scripted fake model (bad JSON, typed numbers, unknown keys, provider outage, retry),
and API behaviour (replace, strict, cache invalidation, structured errors).
The live Anthropic call itself is only covered by its error path in tests; test it once with your key.

## Deploy

- Backend (Render/Railway/Fly): root `backend`, build `pip install -r requirements.txt`,
  start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, set `ANTHROPIC_API_KEY` and `CORS_ORIGINS`.
  Free tiers have ephemeral disks; the sample days are re-seeded on boot, uploaded days may not survive a restart.

- Frontend (Vercel/Netlify): root `frontend`, build `npm run build`, output `dist`,
  set `VITE_API_BASE_URL` to the backend URL. `vercel.json` handles SPA routing.

**Deployed here:** backend on Render (`https://swasthiq-eod-agent-ekcg.onrender.com`), frontend on Vercel (`https://swasthiq-eod-frontend.vercel.app`).
