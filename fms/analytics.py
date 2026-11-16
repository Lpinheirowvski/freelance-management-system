"""Currency-scoped financial calculations. Receipts use payment dates, never project dates."""

from decimal import Decimal, ROUND_HALF_UP
import pandas as pd

from fms.service import CURRENCIES, Service, validate


class Analytics:
    def __init__(self, db):
        self.db = db

    def summary(self, month, currency):
        validate("financial_goals", {"month": month, "currency": currency}, partial=True)
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT
                COALESCE(SUM(CASE WHEN status='Received' AND substr(received_date,1,7)=? THEN amount_cents ELSE 0 END),0) monthly_received_cents,
                COALESCE(SUM(CASE WHEN status='Received' THEN amount_cents ELSE 0 END),0) received_cents,
                COALESCE(SUM(CASE WHEN status='Pending' THEN amount_cents ELSE 0 END),0) pending_cents,
                COALESCE(SUM(CASE WHEN status='Received' AND received_date IS NULL THEN amount_cents ELSE 0 END),0) undated_cents
                FROM payments WHERE currency=?""",
                (month, currency),
            ).fetchone()
            result = dict(row)
            result["estimated_cents"] = conn.execute(
                "SELECT COALESCE(SUM(estimated_cents),0) FROM proposals WHERE currency=? AND status NOT IN ('Accepted','Rejected')",
                (currency,),
            ).fetchone()[0]
            result["contracted_cents"] = conn.execute(
                "SELECT COALESCE(SUM(budget_cents),0) FROM projects WHERE currency=? AND status!='Cancelled'",
                (currency,),
            ).fetchone()[0]
            goal = conn.execute(
                "SELECT amount_cents FROM financial_goals WHERE month=? AND currency=?", (month, currency)
            ).fetchone()
            result["goal_cents"] = goal[0] if goal else 0
            accepted, decided = conn.execute(
                "SELECT COALESCE(SUM(status='Accepted'),0), COALESCE(SUM(status IN ('Accepted','Rejected')),0) FROM proposals WHERE currency=?",
                (currency,),
            ).fetchone()
        result["conversion_rate"] = accepted / decided if decided else None
        result["goal_progress"] = (
            result["monthly_received_cents"] / result["goal_cents"] if result["goal_cents"] else None
        )
        return result

    def revenue(self, currency, group="month"):
        if currency not in CURRENCIES or group not in ("month", "client", "platform"):
            raise ValueError("Unknown currency or revenue grouping.")
        expressions = {
            "month": "substr(pay.received_date,1,7)",
            "client": "c.name || ' (#' || c.id || ')'",
            "platform": "p.platform",
        }
        expression = expressions[group]
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""SELECT {expression} AS label, SUM(pay.amount_cents) AS amount_cents
                FROM payments pay JOIN projects p ON pay.project_id=p.id JOIN clients c ON p.client_id=c.id
                WHERE pay.currency=? AND pay.status='Received' {"AND pay.received_date IS NOT NULL" if group == "month" else ""}
                GROUP BY {expression} ORDER BY label""",
                (currency,),
            ).fetchall()
        frame = pd.DataFrame([dict(r) for r in rows], columns=["label", "amount_cents"])
        frame["revenue"] = frame["amount_cents"] / 100
        return frame

    def profitability(self, currency):
        if currency not in CURRENCIES:
            raise ValueError("Unknown currency.")
        projects = [p for p in Service(self.db).rows("projects") if p["currency"] == currency]
        result = []
        for p in projects:
            cost = int(
                (Decimal(str(p["hours_worked"])) * p["hourly_rate_cents"]).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
            result.append(
                {
                    "project": p["name"],
                    "budget_cents": p["budget_cents"],
                    "labor_value_cents": cost,
                    "surplus_cents": p["budget_cents"] - cost,
                    "margin_percent": (p["budget_cents"] - cost) / p["budget_cents"] * 100
                    if p["budget_cents"]
                    else None,
                    "effective_hourly_rate": p["budget_cents"] / 100 / p["hours_worked"] if p["hours_worked"] else None,
                }
            )
        return pd.DataFrame(result)
