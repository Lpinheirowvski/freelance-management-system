"""Streamlit's real script runner verifies pages, submissions and persistence."""

from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from fms.db import Database
from fms.demo import create_demo
from fms.service import Service

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def ui(tmp_path, monkeypatch):
    path = tmp_path / "demo.sqlite3"
    create_demo(path)
    monkeypatch.setenv("FMS_DB", str(path))
    return AppTest.from_file(APP, default_timeout=20), Service(Database(path))


@pytest.mark.parametrize(
    "page",
    [
        "Overview",
        "Clients",
        "Projects",
        "Proposal pipeline",
        "Kanban board",
        "Financial analytics",
        "Contact history",
        "Settings",
    ],
)
def test_every_page_renders_without_errors(ui, page):
    app, _ = ui
    app.run()
    app.sidebar.radio[0].set_value(page).run()
    assert not app.exception
    assert not app.error
    assert app.title


def test_create_edit_search_delete_client(ui):
    app, service = ui
    app.run()
    app.sidebar.radio[0].set_value("Clients").run()
    next(w for w in app.text_input if w.label == "Client name *").set_value("New Synthetic Client")
    next(w for w in app.button if w.label == "Save record").click().run()
    assert not app.error
    identifier = service.rows("clients")[-1]["id"]
    assert service.get("clients", identifier)["name"] == "New Synthetic Client"
    next(w for w in app.selectbox if w.label == "Record").set_value(identifier).run()
    next(w for w in app.text_input if w.label == "Company").set_value("Synthetic Company")
    next(w for w in app.button if w.label == "Save record").click().run()
    assert service.get("clients", identifier)["company"] == "Synthetic Company"
    next(w for w in app.text_input if w.label == "Search").set_value("New Synthetic Client").run()
    assert len(app.dataframe[0].value) == 1
    next(w for w in app.checkbox if w.label == "Confirm deletion of this record").check().run()
    next(w for w in app.button if w.label == "Delete record").click().run()
    assert not app.exception
    assert identifier not in [r["id"] for r in service.rows("clients")]


def test_project_create_validation_and_kanban_move(ui):
    app, service = ui
    app.run()
    app.sidebar.radio[0].set_value("Projects").run()
    next(w for w in app.text_input if w.label == "Project name *").set_value("Synthetic Integration")
    next(w for w in app.text_input if w.label == "Budget").set_value("invalid")
    next(w for w in app.button if w.label == "Save record").click().run()
    assert app.error
    assert len(service.rows("projects")) == 5
    next(w for w in app.text_input if w.label == "Budget").set_value("123.45")
    next(w for w in app.text_input if w.label == "Technology stack (comma-separated)").set_value("Python, SQL")
    next(w for w in app.button if w.label == "Save record").click().run()
    assert not app.error
    new = service.rows("projects")[-1]
    assert new["budget_cents"] == 12345
    assert service.get("projects", new["id"])["technology_stack"] == ["Python", "SQL"]
    app.sidebar.radio[0].set_value("Kanban board").run()
    next(w for w in app.selectbox if w.key == f"move_{new['id']}").set_value("In progress").run()
    assert service.get("projects", new["id"])["status"] == "In progress"


def test_currency_switch_and_goal_update(ui):
    app, service = ui
    app.run()
    app.sidebar.selectbox[0].set_value("BRL").run()
    assert any("BRL" in str(m.value) for m in app.markdown)
    app.sidebar.radio[0].set_value("Settings").run()
    next(w for w in app.text_input if w.label.startswith("Goal for ")).set_value("20000.50")
    next(w for w in app.button if w.label == "Save goal").click().run()
    assert not app.error
    assert any(g["amount_cents"] == 2000050 and g["currency"] == "BRL" for g in service.rows("financial_goals"))
