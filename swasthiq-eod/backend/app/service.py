"""Use-cases that glue validation, storage, reconciliation and narrative together."""
import hashlib
import json
from datetime import date

from . import config
from .errors import ApiError
from .narrative import generate_narrative
from .reconcile import compute_report
from .validation import BatchError, validate_batch


def _parse_date(value):
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ApiError(422, "invalid_business_date", f"business_date must be YYYY-MM-DD, got {value!r}.")


class Service:
    def __init__(self, db, llm):
        self.db = db
        self.llm = llm

    # ---------- ingestion ----------

    def ingest(self, payload, strict=False, business_date=None):
        clinic_id = None
        if isinstance(payload, dict):
            records = payload.get("records")
            business_date = business_date or payload.get("business_date")
            clinic_id = payload.get("clinic_id")
        else:
            records = payload
        if business_date is not None:
            business_date = _parse_date(business_date)

        try:
            batch = validate_batch(records, business_date, clinic_id)
        except BatchError as e:
            raise ApiError(422, e.code, e.message)

        rejected = [e.to_dict() for e in batch.errors]
        if batch.business_date is None:
            raise ApiError(422, "business_date_required",
                           "No valid rows to infer the day from. Send business_date (YYYY-MM-DD) with the log.", rejected)
        if strict and batch.errors:
            raise ApiError(422, "validation_failed",
                           f"{len(batch.errors)} problem(s) found and strict mode is on, so nothing was stored.", rejected)
        if not batch.visits and batch.total_rows > 0:
            raise ApiError(422, "all_rows_rejected",
                           "Every row was rejected, so nothing was stored and any existing data for this day is untouched.", rejected)

        clinic = batch.clinic_id or config.DEFAULT_CLINIC_ID
        status = self.db.replace_day(clinic, batch.business_date, batch.visits,
                                     batch.total_rows, batch.errors, batch.warnings)
        return {
            "status": status,
            "clinic_id": clinic,
            "business_date": batch.business_date,
            "total_rows": batch.total_rows,
            "accepted_count": len(batch.visits),
            "rejected_count": len(batch.errors),
            "rejected_rows": rejected,
            "warnings": batch.warnings,
        }

    # ---------- reads ----------

    def resolve_clinic(self, business_date, clinic_id=None):
        if clinic_id:
            return clinic_id
        clinics = self.db.find_clinics_for_date(business_date)
        if not clinics:
            raise ApiError(404, "day_not_found", f"No billing log has been ingested for {business_date}.")
        if len(clinics) > 1:
            raise ApiError(400, "clinic_id_required", f"Several clinics have data for {business_date}; pass ?clinic_id=.", clinics)
        return clinics[0]

    def report(self, business_date, clinic_id=None, limit=None):
        business_date = _parse_date(business_date)
        clinic_id = self.resolve_clinic(business_date, clinic_id)
        day = self.db.get_day(clinic_id, business_date)
        if day is None:
            raise ApiError(404, "day_not_found", f"No billing log for {clinic_id} on {business_date}.")
        meta, visits = day
        report = compute_report(visits, limit)
        info = config.CLINICS.get(clinic_id, {"name": clinic_id, "location": "", "owner": ""})
        report.update({
            "clinic_id": clinic_id,
            "business_date": business_date,
            "clinic": info,
            "data_quality": {
                "total_rows": meta["total_rows"],
                "accepted_count": meta["accepted_count"],
                "rejected_count": meta["rejected_count"],
                "rejected_rows": json.loads(meta["rejected_json"]),
                "warnings": json.loads(meta["warnings_json"]),
            },
        })
        return report

    def narrative(self, business_date, clinic_id=None, refresh=False):
        report = self.report(business_date, clinic_id)  # default top-N, independent of ?limit
        h = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()[:16]
        if not refresh:
            cached = self.db.get_narrative(report["clinic_id"], report["business_date"])
            if cached and cached[0] == h:
                return {**cached[1], "cached": True, "report_hash": h}
        result = generate_narrative(report, self.llm)
        result["clinic"] = report["clinic"]
        result["business_date"] = report["business_date"]
        if result["status"] == "success":  # never cache fallbacks; retry the model next time
            self.db.save_narrative(report["clinic_id"], report["business_date"], h, result)
        return {**result, "cached": False, "report_hash": h}

    def days(self):
        return self.db.list_days()
