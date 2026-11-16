import sqlite3
import pytest
from fms.service import cents


def test_project_crud_and_normalized_stack(service, project, db):
    service.save(
        "projects",
        {"name": "O'Brien API", "status": "In progress", "deadline": "2026-12-01"},
        project,
        technology_stack=["Python", "SQL", "python"],
    )
    row = service.get("projects", project)
    assert row["name"] == "O'Brien API"
    assert row["technology_stack"] == ["Python", "SQL"]
    assert row["status"] == "In progress"
    service.delete("projects", project)
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM project_technologies").fetchone()[0] == 0
    assert db.integrity()


@pytest.mark.parametrize(
    "table,data,update",
    [
        ("clients", {"name": "Client"}, {"company": "Example"}),
        ("proposal_templates", {"name": "Intro", "body": "Scope"}, {"body": "New scope"}),
        ("financial_goals", {"month": "2026-11", "currency": "USD", "amount_cents": 10000}, {"amount_cents": 20000}),
    ],
)
def test_standalone_crud(service, table, data, update):
    identifier = service.save(table, data)
    service.save(table, update, identifier)
    assert service.get(table, identifier).items() >= update.items()
    service.delete(table, identifier)
    assert service.rows(table) == []


def test_proposal_contact_payment_crud(service, project):
    client = service.get("projects", project)["client_id"]
    proposal = service.save("proposals", {"client_id": client, "title": "API"})
    contact = service.save(
        "contact_history",
        {
            "client_id": client,
            "proposal_id": proposal,
            "contact_date": "2026-11-01",
            "channel": "Email",
            "summary": "Discussed scope",
        },
    )
    service.save("contact_history", {"next_action": "Call"}, contact)
    assert service.get("contact_history", contact)["next_action"] == "Call"
    with pytest.raises(ValueError, match="linked"):
        service.delete("proposals", proposal)
    service.delete("contact_history", contact)
    service.save("proposals", {"status": "Accepted"}, proposal)
    assert service.get("proposals", proposal)["status"] == "Accepted"
    service.delete("proposals", proposal)
    payment = service.save(
        "payments", {"project_id": project, "currency": "USD", "amount_cents": 10000, "status": "Pending"}
    )
    service.save("payments", {"status": "Received", "received_date": "2026-11-16"}, payment)
    assert service.get("payments", payment)["status"] == "Received"
    with pytest.raises(ValueError, match="linked"):
        service.delete("projects", project)
    service.delete("payments", payment)
    service.delete("projects", project)
    service.delete("clients", client)


@pytest.mark.parametrize(
    "data",
    [
        {"name": ""},
        {"name": "Good", "currency": "EUR"},
        {"budget_cents": -1},
        {"budget_cents": 1.5},
        {"hours_worked": float("nan")},
        {"hours_worked": float("inf")},
        {"hours_worked": -1},
        {"status": "Unknown"},
        {"deadline": "2026-02-30"},
        {"client_id": 999},
        {"unexpected": "x"},
    ],
)
def test_invalid_project_changes_roll_back(service, project, data):
    original = service.get("projects", project)
    with pytest.raises(ValueError):
        service.save("projects", data, project, technology_stack=["Injected"])
    assert service.get("projects", project) == original


def test_currency_and_contact_relationships(service, project):
    with pytest.raises(ValueError):
        service.save("payments", {"project_id": project, "currency": "BRL", "amount_cents": 100, "status": "Pending"})
    other = service.save("clients", {"name": "Other"})
    proposal = service.save("proposals", {"client_id": other, "title": "Other proposal"})
    with pytest.raises(ValueError):
        service.save(
            "contact_history",
            {
                "client_id": 1,
                "proposal_id": proposal,
                "contact_date": "2026-11-01",
                "channel": "Email",
                "summary": "Wrong client",
            },
        )


def test_sql_injection_and_constraints(service, project, db):
    payload = "Robert'); DROP TABLE clients;--"
    identifier = service.save("clients", {"name": payload})
    assert service.get("clients", identifier)["name"] == payload
    with pytest.raises(ValueError):
        service.rows("clients; DROP TABLE projects")
    with db.connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO projects(client_id,name,budget_cents) VALUES(999,'x',-1)")
    assert db.integrity()


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "invalid"])
def test_invalid_money(value):
    with pytest.raises(ValueError):
        cents(value)


def test_exact_rounding_and_goal_upsert(service):
    assert cents("0.105") == 11
    assert cents("123.45") == 12345
    service.set_goal("2026-11", "USD", 10000)
    service.set_goal("2026-11", "USD", 20000)
    assert len(service.rows("financial_goals")) == 1
    assert service.rows("financial_goals")[0]["amount_cents"] == 20000
    with pytest.raises(ValueError):
        service.set_goal("2026-13", "USD", 100)


@pytest.mark.parametrize(
    "column,value", [("deadline", "2026-02-30"), ("deadline", "invalid"), ("hours_worked", -1), ("priority", "Unknown")]
)
def test_database_constraints_also_reject_invalid_direct_writes(db, project, column, value):
    with db.connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"UPDATE projects SET {column}=? WHERE id=?", (value, project))
    assert db.integrity()
