"""Deterministic fictional data. Seeding only creates a new database."""

from datetime import date
from fms.service import PROPOSAL_STATUSES, Service
from fms.storage import new_database


def create_demo(destination):
    today = date.today()
    month = today.strftime("%Y-%m")
    serial_month = today.year * 12 + today.month - 1
    months = [
        f"{(serial_month - offset) // 12:04d}-{(serial_month - offset) % 12 + 1:02d}" for offset in range(5, -1, -1)
    ]
    with new_database(destination) as db:
        db.initialize()
        service = Service(db)
        template = service.save(
            "proposal_templates",
            {
                "name": "Development engagement",
                "body": "Hello,\n\nI can help deliver your project.\n\nScope: [deliverables]\nTimeline: [milestones]\nInvestment: [amount and currency]\n\nNext step: a short discovery call.",
            },
        )
        names = ("Northstar Demo Studio", "Example Orbit Labs", "Fictional Cedar Digital")
        clients = [
            service.save(
                "clients",
                {
                    "name": name,
                    "email": f"demo{i}@example.com",
                    "company": name,
                    "notes": "Synthetic portfolio demonstration data.",
                    "created_at": f"{months[0]}-01",
                },
            )
            for i, name in enumerate(names)
        ]
        projects = [
            ("Analytics workspace", "Upwork", "USD", 540000, "In progress", "High", ["Python", "Streamlit"]),
            ("Commerce API", "Direct", "BRL", 1250000, "In progress", "Urgent", ["Python", "FastAPI"]),
            ("Portfolio refresh", "LinkedIn", "USD", 240000, "Completed", "Medium", ["TypeScript", "React"]),
            ("Infrastructure audit", "Direct", "USD", 320000, "Planned", "Low", ["Docker", "Python"]),
            ("Automation toolkit", "Workana", "BRL", 680000, "On hold", "Medium", ["Python"]),
        ]
        for i, (name, platform, currency, budget, status, priority, stack) in enumerate(projects):
            project = service.save(
                "projects",
                {
                    "client_id": clients[i % 3],
                    "name": name,
                    "platform": platform,
                    "currency": currency,
                    "budget_cents": budget,
                    "hourly_rate_cents": 6000 if currency == "USD" else 15000,
                    "hours_worked": 18 + i * 4,
                    "deadline": f"{month}-28",
                    "status": status,
                    "priority": priority,
                    "description": "Fictional engagement for portfolio demonstration.",
                    "next_action": "Share the next milestone preview.",
                    "created_at": f"{months[0]}-01",
                },
                technology_stack=stack,
            )
            # Split half the budget across six months without changing total receivables.
            paid = budget // 2
            allocated = 0
            for index, receipt_month in enumerate(months):
                amount = paid * (index + 1) // 21 if index < 5 else paid - allocated
                allocated += amount
                service.save(
                    "payments",
                    {
                        "project_id": project,
                        "currency": currency,
                        "amount_cents": amount,
                        "status": "Received",
                        "received_date": f"{receipt_month}-01",
                    },
                )
            service.save(
                "payments",
                {
                    "project_id": project,
                    "currency": currency,
                    "amount_cents": budget - budget // 2,
                    "status": "Pending",
                    "due_date": f"{month}-28",
                },
            )
        for i, status in enumerate(PROPOSAL_STATUSES):
            proposal = service.save(
                "proposals",
                {
                    "client_id": clients[i % 3],
                    "title": (
                        "Customer portal",
                        "Data integration",
                        "API modernization",
                        "Cloud migration",
                        "Reporting hub",
                        "Mobile prototype",
                    )[i],
                    "status": status,
                    "platform": ("Direct", "Upwork", "LinkedIn")[i % 3],
                    "currency": "USD" if i % 2 == 0 else "BRL",
                    "estimated_cents": 200000 + i * 80000,
                    "body": "Synthetic proposal. Scope and milestones to be agreed.",
                    "next_action": "Schedule discovery call.",
                    "follow_up": f"{month}-28",
                    "template_id": template,
                },
            )
            service.save(
                "contact_history",
                {
                    "client_id": clients[i % 3],
                    "proposal_id": proposal,
                    "contact_date": f"{month}-01",
                    "channel": "Email",
                    "summary": "Fictional discovery conversation.",
                    "next_action": "Follow up with scope.",
                },
            )
        service.set_goal(month, "USD", 800000)
        service.set_goal(month, "BRL", 1500000)
