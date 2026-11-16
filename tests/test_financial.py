from fms.analytics import Analytics


def test_month_boundaries_currency_and_undated_receipts(db, service, project):
    for received, amount in [
        ("2026-10-31", 10000),
        ("2026-11-01", 20000),
        ("2026-11-30", 30000),
        ("2026-12-01", 40000),
        (None, 5000),
    ]:
        service.save(
            "payments",
            {
                "project_id": project,
                "currency": "USD",
                "amount_cents": amount,
                "status": "Received",
                "received_date": received,
            },
        )
    service.save(
        "payments",
        {"project_id": project, "currency": "USD", "amount_cents": 9000, "status": "Pending", "due_date": "2026-11-15"},
    )
    brl = service.save("projects", {"client_id": 1, "name": "BRL", "currency": "BRL"})
    service.save(
        "payments",
        {
            "project_id": brl,
            "currency": "BRL",
            "amount_cents": 999999,
            "status": "Received",
            "received_date": "2026-11-01",
        },
    )
    service.set_goal("2026-11", "USD", 100000)
    analytics = Analytics(db)
    summary = analytics.summary("2026-11", "USD")
    assert summary["monthly_received_cents"] == 50000
    assert summary["received_cents"] == 105000
    assert summary["undated_cents"] == 5000
    assert summary["pending_cents"] == 9000
    assert summary["goal_progress"] == 0.5
    assert analytics.summary("2026-11", "BRL")["monthly_received_cents"] == 999999
    assert analytics.revenue("USD").set_index("label").loc["2026-11", "amount_cents"] == 50000
    assert analytics.revenue("USD", "client")["amount_cents"].sum() == 105000
    assert analytics.revenue("USD", "platform")["amount_cents"].sum() == 105000


def test_proposals_and_profitability(service, project, db):
    for status, amount in [
        ("Accepted", 20000),
        ("Rejected", 90000),
        ("Negotiation", 30000),
        ("Awaiting response", 40000),
    ]:
        service.save("proposals", {"client_id": 1, "title": status, "status": status, "estimated_cents": amount})
    analytics = Analytics(db)
    summary = analytics.summary("2026-11", "USD")
    assert summary["conversion_rate"] == 0.5
    assert summary["estimated_cents"] == 70000
    row = analytics.profitability("USD").iloc[0]
    assert row["labor_value_cents"] == 20000
    assert row["surplus_cents"] == 80000
    assert row["margin_percent"] == 80
    assert row["effective_hourly_rate"] == 100


def test_empty_analytics(db):
    analytics = Analytics(db)
    summary = analytics.summary("2026-11", "USD")
    assert summary["goal_progress"] is None
    assert summary["conversion_rate"] is None
    assert summary["monthly_received_cents"] == 0
    assert analytics.revenue("BRL").empty
    assert analytics.profitability("USD").empty
