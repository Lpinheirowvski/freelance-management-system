from io import BytesIO
import json
import pytest
from openpyxl import load_workbook
import freelancer_manager as legacy
from fms.exporting import csv_export, excel_export


def test_exports_preserve_currency_and_neutralize_formulas(service, project, db):
    service.save("clients", {"name": "=1+1", "notes": " @SUM(A1:A2)"})
    csv = csv_export(service.rows("clients")).decode("utf-8-sig")
    assert "'=1+1" in csv
    assert "' @SUM(A1:A2)" in csv
    book = load_workbook(BytesIO(excel_export(db)))
    assert "projects" in book.sheetnames
    assert book["clients"]["B3"].value == "'=1+1"
    assert book["clients"]["B3"].data_type == "s"
    headers = [cell.value for cell in book["projects"][1]]
    assert book["projects"].cell(2, headers.index("currency") + 1).value == "USD"


def test_legacy_monthly_goal_excludes_old_and_undated():
    rows = [
        {"pago": True, "total": 100, "data_pagamento": "01/11/2026"},
        {"pago": True, "total": 200, "data_pagamento": "31/10/2026"},
        {"pago": True, "total": 300},
        {"pago": False, "total": 400, "data_pagamento": "01/11/2026"},
        {"pago": True, "total": 500, "data_pagamento": "invalid"},
    ]
    assert legacy.recebido_no_mes(rows, "11/2026") == 100


def test_legacy_atomic_save_and_corruption_refusal(tmp_path, monkeypatch):
    path = tmp_path / "legacy.json"
    monkeypatch.setattr(legacy, "ARQUIVO", str(path))
    legacy.salvar_dados([{"nome": "Example"}])
    assert legacy.carregar_dados() == [{"nome": "Example"}]
    original = path.read_bytes()
    with pytest.raises(ValueError):
        legacy.salvar_dados([{"bad": float("nan")}])
    assert path.read_bytes() == original
    path.write_text("{bad")
    with pytest.raises(ValueError, match="preservado"):
        legacy.carregar_dados()
    assert path.read_text() == "{bad"


def test_legacy_payment_records_date(tmp_path, monkeypatch):
    path = tmp_path / "legacy.json"
    monkeypatch.setattr(legacy, "ARQUIVO", str(path))
    monkeypatch.setattr("builtins.input", lambda _: "1")
    rows = [{"id": 1, "nome": "Example", "projeto": "API", "total": 50, "pago": False}]
    legacy.registrar_pagamento(rows)
    assert rows[0]["pago"]
    assert rows[0]["data_pagamento"]
    assert json.loads(path.read_text())[0]["data_pagamento"]
