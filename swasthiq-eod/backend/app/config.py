"""All settings in one place. Everything can be overridden with environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "eod.db"))
SAMPLE_DIR = BASE_DIR / "sample_data"

# Hour-of-day bucketing. The brief says timestamps are UTC and "used for hour-of-day
# bucketing", so the default is 0 (bucket in UTC). Set to 330 to bucket in IST.
HOUR_BUCKET_OFFSET_MINUTES = int(os.getenv("HOUR_BUCKET_OFFSET_MINUTES", "0"))

TOP_N = 5
DEFAULT_CLINIC_ID = os.getenv("DEFAULT_CLINIC_ID", "CLN-KNP-014")

# Two drug names are treated as the same drug (typo) if their similarity is >= this.
DRUG_FUZZY_THRESHOLD = 0.9

# Display info for clinics we know about. Unknown clinics fall back to their id.
CLINICS = {
    "CLN-KNP-014": {
        "name": "Mehta Multi-Specialty Clinic",
        "location": "Kanpur, Uttar Pradesh",
        "owner": "Dr. Anand Mehta",
    }
}

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))

CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
SEED_SAMPLE_DATA = os.getenv("SEED_SAMPLE_DATA", "1") == "1"
