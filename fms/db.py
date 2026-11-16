"""SQLite connections, schema and integrity checks. No application data is logged."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3

SCHEMA_VERSION = 2
SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    email TEXT NOT NULL DEFAULT '', company TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (date('now'))
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE RESTRICT,
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    description TEXT NOT NULL DEFAULT '', platform TEXT NOT NULL DEFAULT 'Direct',
    currency TEXT NOT NULL DEFAULT 'USD' CHECK(currency IN ('USD','BRL')),
    budget_cents INTEGER NOT NULL DEFAULT 0 CHECK(typeof(budget_cents)='integer' AND budget_cents>=0),
    hourly_rate_cents INTEGER NOT NULL DEFAULT 0 CHECK(typeof(hourly_rate_cents)='integer' AND hourly_rate_cents>=0),
    hours_worked REAL NOT NULL DEFAULT 0 CHECK(hours_worked>=0 AND hours_worked<1e9),
    deadline TEXT CHECK(deadline IS NULL OR (length(deadline)=10 AND date(deadline,'+0 days') IS deadline)),
    priority TEXT NOT NULL DEFAULT 'Medium' CHECK(priority IN ('Low','Medium','High','Urgent')),
    status TEXT NOT NULL DEFAULT 'Planned' CHECK(status IN ('Planned','In progress','On hold','Completed','Cancelled')),
    notes TEXT NOT NULL DEFAULT '', next_action TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (date('now')),
    UNIQUE(id,currency)
);
CREATE TABLE IF NOT EXISTS technologies (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(length(trim(name))>0)
);
CREATE TABLE IF NOT EXISTS project_technologies (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    technology_id INTEGER NOT NULL REFERENCES technologies(id) ON DELETE RESTRICT,
    PRIMARY KEY(project_id,technology_id)
);
CREATE TABLE IF NOT EXISTS proposal_templates (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL CHECK(length(trim(name))>0),
    body TEXT NOT NULL CHECK(length(trim(body))>0)
);
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE RESTRICT,
    title TEXT NOT NULL CHECK(length(trim(title))>0),
    status TEXT NOT NULL DEFAULT 'Opportunity identified'
        CHECK(status IN ('Opportunity identified','Proposal submitted','Awaiting response','Negotiation','Accepted','Rejected')),
    platform TEXT NOT NULL DEFAULT 'Direct',
    currency TEXT NOT NULL DEFAULT 'USD' CHECK(currency IN ('USD','BRL')),
    estimated_cents INTEGER NOT NULL DEFAULT 0 CHECK(typeof(estimated_cents)='integer' AND estimated_cents>=0),
    body TEXT NOT NULL DEFAULT '', next_action TEXT NOT NULL DEFAULT '',
    follow_up TEXT CHECK(follow_up IS NULL OR (length(follow_up)=10 AND date(follow_up,'+0 days') IS follow_up)),
    template_id INTEGER REFERENCES proposal_templates(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (date('now')), UNIQUE(id,client_id)
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    currency TEXT NOT NULL CHECK(currency IN ('USD','BRL')),
    amount_cents INTEGER NOT NULL CHECK(typeof(amount_cents)='integer' AND amount_cents>=0),
    status TEXT NOT NULL CHECK(status IN ('Pending','Received')),
    due_date TEXT CHECK(due_date IS NULL OR (length(due_date)=10 AND date(due_date,'+0 days') IS due_date)),
    received_date TEXT CHECK(received_date IS NULL OR (length(received_date)=10 AND date(received_date,'+0 days') IS received_date)),
    notes TEXT NOT NULL DEFAULT '',
    CHECK(status='Received' OR received_date IS NULL),
    FOREIGN KEY(project_id,currency) REFERENCES projects(id,currency) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS contact_history (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE RESTRICT,
    proposal_id INTEGER,
    contact_date TEXT NOT NULL CHECK(length(contact_date)=10 AND date(contact_date,'+0 days') IS contact_date),
    channel TEXT NOT NULL CHECK(length(trim(channel))>0),
    summary TEXT NOT NULL CHECK(length(trim(summary))>0),
    next_action TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(proposal_id,client_id) REFERENCES proposals(id,client_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS financial_goals (
    id INTEGER PRIMARY KEY,
    month TEXT NOT NULL CHECK(length(month)=7 AND date(month||'-01','+0 days') IS (month||'-01')),
    currency TEXT NOT NULL CHECK(currency IN ('USD','BRL')),
    amount_cents INTEGER NOT NULL CHECK(typeof(amount_cents)='integer' AND amount_cents>0),
    UNIQUE(month,currency)
);
CREATE TABLE IF NOT EXISTS migration_runs (
    id INTEGER PRIMARY KEY, source_sha256 TEXT NOT NULL UNIQUE,
    imported_count INTEGER NOT NULL, migrated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_projects_client ON projects(client_id);
CREATE INDEX IF NOT EXISTS idx_projects_filters ON projects(status,priority,platform,deadline);
CREATE INDEX IF NOT EXISTS idx_proposals_client ON proposals(client_id);
CREATE INDEX IF NOT EXISTS idx_proposals_pipeline ON proposals(status,platform,follow_up);
CREATE INDEX IF NOT EXISTS idx_proposals_template ON proposals(template_id);
CREATE INDEX IF NOT EXISTS idx_payments_project ON payments(project_id,currency);
CREATE INDEX IF NOT EXISTS idx_payments_month ON payments(currency,status,received_date);
CREATE INDEX IF NOT EXISTS idx_contacts_client ON contact_history(client_id,contact_date);
CREATE INDEX IF NOT EXISTS idx_contacts_proposal ON contact_history(proposal_id,client_id);
CREATE INDEX IF NOT EXISTS idx_stack_technology ON project_technologies(technology_id);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if version not in (0, SCHEMA_VERSION) or (version == 0 and tables):
                raise ValueError("Unsupported database. Select a new path or a valid v2 backup.")
            conn.executescript(SCHEMA)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def integrity(self):
        with self.connect() as conn:
            checks = [r[0] for r in conn.execute("PRAGMA integrity_check")]
            foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
        return checks == ["ok"] and not foreign_keys
