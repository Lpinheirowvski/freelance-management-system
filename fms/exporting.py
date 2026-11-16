"""In-memory exports with spreadsheet formula injection protection."""

from io import BytesIO
import pandas as pd
from fms.service import FIELDS, Service


def safe_frame(rows):
    frame = pd.DataFrame(rows)
    # Excel and CSV readers may interpret leading operators as formulas.
    return frame.map(
        lambda v: "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else v
    )


def csv_export(rows):
    return safe_frame(rows).to_csv(index=False).encode("utf-8-sig")


def excel_export(db):
    output = BytesIO()
    service = Service(db)
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for table in FIELDS:
            frame = safe_frame(service.rows(table))
            frame.to_excel(writer, sheet_name=table, index=False)
        with db.connect() as conn:
            for table in ("technologies", "project_technologies"):
                safe_frame([dict(r) for r in conn.execute(f"SELECT * FROM {table}")]).to_excel(
                    writer, sheet_name=table, index=False
                )
    return output.getvalue()
