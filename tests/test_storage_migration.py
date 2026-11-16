import json
import sqlite3
import pytest
from fms.db import Database
from fms.migration import migrate
from fms.storage import backup_database, restore_database, validate_backup
from fms.service import Service
from fms.analytics import Analytics
from fms.demo import create_demo


def legacy_file(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "nome": "Example",
                    "projeto": "API",
                    "horas": 10,
                    "valor_hora": 20,
                    "total": 200,
                    "pago": True,
                    "data": "01/10/2026",
                },
                {
                    "id": 2,
                    "nome": "Example",
                    "projeto": "Web",
                    "horas": 5,
                    "valor_hora": 20,
                    "total": 100,
                    "pago": False,
                    "data": "01/11/2026",
                },
                {
                    "id": 3,
                    "nome": "Other",
                    "projeto": "SQL",
                    "horas": 2,
                    "valor_hora": 20,
                    "total": 40,
                    "pago": True,
                    "data": "01/11/2026",
                    "data_pagamento": "16/11/2026",
                },
            ]
        )
    )
    return path


def test_migration_preserves_source_and_unknown_payment_date(tmp_path):
    source = legacy_file(tmp_path)
    original = source.read_bytes()
    target = tmp_path / "v2.sqlite3"
    result = migrate(source, target)
    assert source.read_bytes() == original
    from pathlib import Path

    assert Path(result["backup"]).read_bytes() == original
    assert result["records"] == 3
    db = Database(target)
    assert db.integrity()
    assert len(Service(db).rows("clients")) == 2
    assert len(Service(db).rows("projects")) == 3
    summary = Analytics(db).summary("2026-11", "USD")
    assert summary["monthly_received_cents"] == 4000
    assert summary["received_cents"] == 24000
    assert summary["pending_cents"] == 10000
    with pytest.raises(ValueError, match="exists"):
        migrate(source, target)
    assert len(Service(db).rows("projects")) == 3


@pytest.mark.parametrize("mutation", ["malformed", "invalid_second", "not_list", "duplicate_id", "negative_hours"])
def test_migration_failure_never_publishes_partial_data(tmp_path, mutation):
    source = legacy_file(tmp_path)
    rows = json.loads(source.read_text())
    if mutation == "malformed":
        source.write_text("{")
    elif mutation == "not_list":
        source.write_text("{}")
    else:
        if mutation == "invalid_second":
            rows[1]["total"] = -1
        elif mutation == "duplicate_id":
            rows[1]["id"] = 1
        else:
            rows[1]["horas"] = -1
        source.write_text(json.dumps(rows))
    original = source.read_bytes()
    with pytest.raises(ValueError):
        migrate(source, tmp_path / "new.sqlite3")
    assert source.read_bytes() == original
    assert not (tmp_path / "new.sqlite3").exists()


def test_backup_restore_and_overwrite_protection(db, service, project, tmp_path):
    target = tmp_path / "backup.sqlite3"
    backup_database(db.path, target)
    validate_backup(target)
    restored = tmp_path / "restored.sqlite3"
    restore_database(target, restored)
    assert Service(Database(restored)).get("projects", project)["name"] == "Example API"
    with pytest.raises(ValueError, match="exists"):
        restore_database(target, db.path)
    assert service.get("projects", project)["name"] == "Example API"


def test_reject_corrupt_foreign_schema_and_trigger_backups(tmp_path):
    source = tmp_path / "bad.sqlite3"
    source.write_bytes(b"not sqlite")
    with pytest.raises(ValueError):
        restore_database(source, tmp_path / "restored.sqlite3")
    source.unlink()
    db = Database(source)
    db.initialize()
    with db.connect() as conn:
        conn.execute("CREATE TRIGGER surprise AFTER INSERT ON clients BEGIN DELETE FROM clients; END")
    with pytest.raises(ValueError, match="schema"):
        validate_backup(source)
    assert not (tmp_path / "restored.sqlite3").exists()


def test_unknown_schema_is_not_modified(tmp_path):
    source = tmp_path / "foreign.sqlite3"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE foreign_data(id INTEGER)")
    with pytest.raises(ValueError):
        Database(source).initialize()
    with sqlite3.connect(source) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("foreign_data",)]


def test_demo_is_synthetic_and_non_overwriting(tmp_path):
    path = tmp_path / "demo.sqlite3"
    create_demo(path)
    service = Service(Database(path))
    assert len(service.rows("projects")) == 5
    assert len(service.rows("proposals")) == 6
    assert all(c["email"].endswith("@example.com") for c in service.rows("clients"))
    with pytest.raises(ValueError):
        create_demo(path)


def test_integrity_detects_dangling_relationship_and_restore_rejects_it(db, project, tmp_path):
    with sqlite3.connect(db.path) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("UPDATE projects SET client_id=999 WHERE id=?", (project,))
    assert not db.integrity()
    with pytest.raises(ValueError, match="integrity"):
        restore_database(db.path, tmp_path / "rejected.sqlite3")
    assert not (tmp_path / "rejected.sqlite3").exists()


def test_demo_receipts_span_six_months_without_overstating_budgets(tmp_path):
    from fms.analytics import Analytics

    db = Database(tmp_path / "demo.sqlite3")
    create_demo(db.path)
    assert len(Analytics(db).revenue("USD")) == 6
    service = Service(db)
    for project in service.rows("projects"):
        payments = [p for p in service.rows("payments") if p["project_id"] == project["id"]]
        assert sum(p["amount_cents"] for p in payments) == project["budget_cents"]
