"""Validated CRUD and transaction boundaries shared by the web interface and tools."""

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import logging
import math
import sqlite3

logger = logging.getLogger(__name__)
CURRENCIES = ("USD", "BRL")
PROJECT_STATUSES = ("Planned", "In progress", "On hold", "Completed", "Cancelled")
PROPOSAL_STATUSES = (
    "Opportunity identified",
    "Proposal submitted",
    "Awaiting response",
    "Negotiation",
    "Accepted",
    "Rejected",
)
PRIORITIES = ("Low", "Medium", "High", "Urgent")
FIELDS = {
    "clients": {"name", "email", "company", "notes", "created_at"},
    "projects": {
        "client_id",
        "name",
        "description",
        "platform",
        "currency",
        "budget_cents",
        "hourly_rate_cents",
        "hours_worked",
        "deadline",
        "priority",
        "status",
        "notes",
        "next_action",
        "created_at",
    },
    "proposals": {
        "client_id",
        "title",
        "status",
        "platform",
        "currency",
        "estimated_cents",
        "body",
        "next_action",
        "follow_up",
        "template_id",
        "created_at",
    },
    "payments": {"project_id", "currency", "amount_cents", "status", "due_date", "received_date", "notes"},
    "contact_history": {"client_id", "proposal_id", "contact_date", "channel", "summary", "next_action"},
    "financial_goals": {"month", "currency", "amount_cents"},
    "proposal_templates": {"name", "body"},
}
REQUIRED = {
    "clients": ("name",),
    "projects": ("client_id", "name"),
    "proposals": ("client_id", "title"),
    "payments": ("project_id", "currency", "amount_cents", "status"),
    "contact_history": ("client_id", "contact_date", "channel", "summary"),
    "financial_goals": ("month", "currency", "amount_cents"),
    "proposal_templates": ("name", "body"),
}


def cents(value):
    """Convert decimal input to exact integer minor units; reject non-finite input."""
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > Decimal("1000000000000"):
            raise ValueError("Amount must be finite, non-negative and at most one trillion.")
        return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("Enter a valid monetary amount.") from exc


def validate(table, data, partial=False):
    if table not in FIELDS:
        raise ValueError("Unknown entity.")
    if not data or set(data) - FIELDS[table]:
        raise ValueError("Empty input or unknown field.")
    result = dict(data)
    if not partial:
        for key in REQUIRED[table]:
            if result.get(key) is None:
                raise ValueError(f"{key} is required.")
    for key, value in result.items():
        if key in ("name", "title", "channel", "summary", "body"):
            if not isinstance(value, str) or (key in REQUIRED[table] and not value.strip()):
                raise ValueError(f"{key} cannot be empty.")
        if key.endswith("_cents"):
            if type(value) is not int or not 0 <= value <= 100_000_000_000_000:
                raise ValueError(f"{key} must be a non-negative integer in cents.")
        if key.endswith("_id") and value is not None and (type(value) is not int or value < 1):
            raise ValueError(f"{key} must be a positive integer.")
        if (
            key in ("deadline", "follow_up", "due_date", "received_date", "contact_date", "created_at")
            and value is not None
        ):
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} must use YYYY-MM-DD.") from exc
        if key == "currency" and value not in CURRENCIES:
            raise ValueError("Currency must be USD or BRL.")
        if key == "priority" and value not in PRIORITIES:
            raise ValueError("Unknown priority.")
        if key == "status":
            options = {
                "projects": PROJECT_STATUSES,
                "proposals": PROPOSAL_STATUSES,
                "payments": ("Pending", "Received"),
            }
            if value not in options.get(table, ()):
                raise ValueError("Unknown status.")
        if key == "hours_worked":
            try:
                valid = not isinstance(value, bool) and math.isfinite(float(value)) and 0 <= float(value) < 1e9
            except (ValueError, TypeError):
                valid = False
            if not valid:
                raise ValueError("Hours must be finite and non-negative.")
        if key == "month":
            try:
                if len(value) != 7 or date.fromisoformat(value + "-01").strftime("%Y-%m") != value:
                    raise ValueError()
            except (ValueError, TypeError) as exc:
                raise ValueError("Month must use YYYY-MM.") from exc
    if table == "financial_goals" and result.get("amount_cents") == 0:
        raise ValueError("Goal must be greater than zero.")
    return result


class Service:
    def __init__(self, db):
        self.db = db

    def rows(self, table):
        if table not in FIELDS:
            raise ValueError("Unknown entity.")
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id")]

    def get(self, table, entity_id):
        if table not in FIELDS:
            raise ValueError("Unknown entity.")
        with self.db.connect() as conn:
            row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (entity_id,)).fetchone()
            if row is None:
                raise ValueError("Record no longer exists.")
            result = dict(row)
            if table == "projects":
                result["technology_stack"] = [
                    r[0]
                    for r in conn.execute(
                        "SELECT t.name FROM technologies t JOIN project_technologies pt ON pt.technology_id=t.id WHERE pt.project_id=? ORDER BY t.name",
                        (entity_id,),
                    )
                ]
            return result

    @staticmethod
    def _stack(conn, project_id, stack):
        conn.execute("DELETE FROM project_technologies WHERE project_id=?", (project_id,))
        for name in dict.fromkeys(s.strip() for s in stack if s.strip()):
            conn.execute("INSERT OR IGNORE INTO technologies(name) VALUES(?)", (name,))
            conn.execute(
                "INSERT OR IGNORE INTO project_technologies VALUES(?,(SELECT id FROM technologies WHERE name=? COLLATE NOCASE))",
                (project_id, name),
            )

    def save(self, table, data, entity_id=None, technology_stack=None):
        data = validate(table, data, partial=entity_id is not None)
        if technology_stack is not None and (
            table != "projects"
            or not isinstance(technology_stack, (list, tuple))
            or any(not isinstance(s, str) for s in technology_stack)
        ):
            raise ValueError("Technology stack must be a list of names for a project.")
        try:
            with self.db.connect() as conn:
                if entity_id is None:
                    keys = ",".join(data)
                    marks = ",".join("?" for _ in data)
                    entity_id = conn.execute(
                        f"INSERT INTO {table} ({keys}) VALUES({marks})", tuple(data.values())
                    ).lastrowid
                else:
                    assignments = ",".join(f"{k}=?" for k in data)
                    changed = conn.execute(
                        f"UPDATE {table} SET {assignments} WHERE id=?", (*data.values(), entity_id)
                    ).rowcount
                    if not changed:
                        raise ValueError("Record no longer exists.")
                if technology_stack is not None:
                    self._stack(conn, entity_id, technology_stack)
            logger.info("Saved %s record", table)
            return entity_id
        except sqlite3.IntegrityError as exc:
            logger.warning("Constraint prevented saving %s", table)
            raise ValueError(
                "Invalid relationship, duplicate goal, or constrained value. Payments must use the project currency; contacts must match the proposal client."
            ) from exc

    def delete(self, table, entity_id):
        if table not in FIELDS:
            raise ValueError("Unknown entity.")
        try:
            with self.db.connect() as conn:
                if not conn.execute(f"DELETE FROM {table} WHERE id=?", (entity_id,)).rowcount:
                    raise ValueError("Record no longer exists.")
        except sqlite3.IntegrityError as exc:
            raise ValueError("This record has linked records. Remove those links first.") from exc
        logger.info("Deleted %s record", table)

    def set_goal(self, month, currency, amount_cents):
        data = validate("financial_goals", dict(month=month, currency=currency, amount_cents=amount_cents))
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO financial_goals(month,currency,amount_cents) VALUES(?,?,?) ON CONFLICT(month,currency) DO UPDATE SET amount_cents=excluded.amount_cents",
                tuple(data.values()),
            )
