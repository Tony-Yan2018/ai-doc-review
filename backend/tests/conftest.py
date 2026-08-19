import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEST_ROOT = Path(__file__).parent / ".runtime" / str(os.getpid())
TEST_ROOT.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_ROOT / 'test.sqlite3'}"
os.environ["UPLOAD_DIR"] = str(TEST_ROOT / "uploads")
os.environ["JOB_RETRY_BASE_SECONDS"] = "0"

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
