import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"


def load_sample(day):
    return json.loads((SAMPLES / f"billing_log_{day}.json").read_text())


def make_row(**over):
    row = {
        "clinic_id": "CLN-T-1", "visit_id": "V-1", "timestamp": "2026-07-27T10:00:00Z", "doctor_id": "D1",
        "line_items": [{"drug_name": "PARACETAMOL", "qty": 2, "unit_price_paise": 2000}],
        "payment_mode": "cash", "amount_paid_paise": 4000, "discount_paise": 0, "is_refund": False,
    }
    row.update(over)
    return row


class FakeLLM:
    """Scripted model: returns the given replies in order (or raises if an item is an Exception)."""
    model = "fake-model"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def make_client(tmp_path):
    def _make(llm=None, seed=False):
        return TestClient(create_app(str(tmp_path / "t.db"), llm=llm, seed=seed))
    return _make


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def seeded(make_client):
    return make_client(seed=True)
