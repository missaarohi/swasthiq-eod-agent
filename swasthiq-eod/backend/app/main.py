"""HTTP layer. Routes stay thin: parse the request, call Service, return JSON."""
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config
from .db import Database
from .errors import ApiError
from .llm import default_llm
from .service import Service

log = logging.getLogger("eod")


def seed_samples(service):
    """Load the three sample clinic-days on first start so the live demo is not empty."""
    import json
    for f in sorted(Path(config.SAMPLE_DIR).glob("billing_log_*.json")):
        m = re.search(r"(\d{4}-\d{2}-\d{2})", f.name)
        try:
            service.ingest({"records": json.loads(f.read_text()), "business_date": m.group(1) if m else None,
                            "clinic_id": config.DEFAULT_CLINIC_ID})
        except Exception:  # a bad sample must not stop the API from booting
            log.exception("could not seed %s", f.name)


def create_app(db_path=None, llm="default", seed=None):
    db = Database(db_path or config.DB_PATH)
    service = Service(db, default_llm() if llm == "default" else llm)
    if (config.SEED_SAMPLE_DATA if seed is None else seed) and not db.list_days():
        seed_samples(service)

    app = FastAPI(title="EOD Billing & Analytics API", version="1.0.0")
    app.state.service = service
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(ApiError)
    async def api_error(_: Request, e: ApiError):
        return JSONResponse(e.to_body(), status_code=e.status_code)

    @app.exception_handler(RequestValidationError)
    async def bad_request(_: Request, e: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]} for err in e.errors()]
        return JSONResponse({"error": {"code": "invalid_request", "message": "Request could not be parsed.", "details": details}},
                            status_code=422)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, e: Exception):
        log.exception("unhandled error")
        return JSONResponse({"error": {"code": "internal_error", "message": "Unexpected server error.", "details": []}},
                            status_code=500)

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "llm_configured": service.llm is not None}

    @app.post("/api/v1/days")
    def ingest(payload: Any = Body(...), strict: bool = False, business_date: str | None = None):
        result = service.ingest(payload, strict=strict, business_date=business_date)
        return JSONResponse(result, status_code=201 if result["status"] == "created" else 200)

    @app.get("/api/v1/days")
    def list_days():
        return {"days": service.days()}

    @app.get("/api/v1/days/{business_date}/report")
    def report(business_date: str, clinic_id: str | None = None, limit: int = Query(config.TOP_N, ge=1, le=50)):
        return service.report(business_date, clinic_id, limit)

    @app.get("/api/v1/days/{business_date}/narrative")
    def narrative(business_date: str, clinic_id: str | None = None, refresh: bool = False):
        return service.narrative(business_date, clinic_id, refresh)

    return app


app = create_app()
