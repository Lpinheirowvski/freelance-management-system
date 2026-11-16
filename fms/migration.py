"""Explicit, all-or-nothing migration of the original Portuguese v1 JSON format."""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

from fms.service import Service, cents
from fms.storage import new_database


def migrate(source, destination):
    source = Path(source)
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        records = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Legacy file must contain valid UTF-8 JSON.") from exc
    if not isinstance(records, list):
        raise ValueError("Legacy JSON must contain a list of projects.")
    prepared = []
    ids = set()
    for position, row in enumerate(records, 1):
        try:
            if not isinstance(row, dict) or type(row["id"]) is not int or row["id"] < 1 or row["id"] in ids:
                raise ValueError()
            ids.add(row["id"])
            if type(row["pago"]) is not bool or not all(
                isinstance(row[k], str) and row[k].strip() for k in ("nome", "projeto")
            ):
                raise ValueError()
            created = datetime.strptime(row["data"], "%d/%m/%Y").date().isoformat()
            paid_date = row.get("data_pagamento")
            if paid_date:
                paid_date = datetime.strptime(paid_date, "%d/%m/%Y").date().isoformat()
            prepared.append((row, created, paid_date, cents(row["total"]), cents(row["valor_hora"])))
        except (KeyError, ValueError, TypeError, OverflowError) as exc:
            raise ValueError(f"Invalid legacy record at position {position}; nothing was imported.") from exc
    if Path(destination).exists():
        raise ValueError("Destination already exists. Choose a new filename.")
    # Keep an exact, immutable-by-convention copy next to the source. Never rewrite JSON.
    copy = source.with_name(f"{source.name}.{digest[:12]}.bak")
    try:
        descriptor = os.open(copy, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if copy.read_bytes() != raw:
            raise ValueError("Existing source backup differs. Resolve the conflict before migration.")
    else:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
    with new_database(destination) as db:
        db.initialize()
        service = Service(db)
        clients = {}
        for row, created, paid_date, amount, rate in prepared:
            name = row["nome"].strip()
            if name not in clients:
                clients[name] = service.save("clients", {"name": name, "created_at": created})
            project = service.save(
                "projects",
                {
                    "client_id": clients[name],
                    "name": row["projeto"],
                    "currency": "USD",
                    "hours_worked": row["horas"],
                    "hourly_rate_cents": rate,
                    "budget_cents": amount,
                    "created_at": created,
                    "notes": f"Migrated from v1; legacy ID: {row['id']}. Original JSON retained.",
                },
            )
            service.save(
                "payments",
                {
                    "project_id": project,
                    "currency": "USD",
                    "amount_cents": amount,
                    "status": "Received" if row["pago"] else "Pending",
                    "received_date": paid_date if row["pago"] else None,
                    "notes": "Legacy payment date unknown; excluded from monthly revenue."
                    if row["pago"] and not paid_date
                    else "Migrated from v1.",
                },
            )
        with db.connect() as conn:
            conn.execute("INSERT INTO migration_runs(source_sha256,imported_count) VALUES(?,?)", (digest, len(records)))
    return {"records": len(records), "source_sha256": digest, "backup": str(copy), "database": str(destination)}
