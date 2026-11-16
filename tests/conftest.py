import pytest
from fms.db import Database
from fms.service import Service


@pytest.fixture
def db(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    db.initialize()
    return db


@pytest.fixture
def service(db):
    return Service(db)


@pytest.fixture
def project(service):
    client = service.save("clients", {"name": "Example Client"})
    return service.save(
        "projects",
        {
            "client_id": client,
            "name": "Example API",
            "budget_cents": 100000,
            "hourly_rate_cents": 2000,
            "hours_worked": 10,
        },
    )
