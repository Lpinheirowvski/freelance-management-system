"""Streamlit presentation layer; persistence and finance live in separate modules."""

from datetime import date, datetime
from html import escape
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
import uuid

import pandas as pd
import plotly.express as px
import streamlit as st

from fms.analytics import Analytics
from fms.db import Database
from fms.exporting import csv_export, excel_export
from fms.service import CURRENCIES, FIELDS, PRIORITIES, PROJECT_STATUSES, PROPOSAL_STATUSES, Service, cents
from fms.storage import backup_database, restore_database

PAGES = (
    "Overview",
    "Clients",
    "Projects",
    "Proposal pipeline",
    "Kanban board",
    "Financial analytics",
    "Contact history",
    "Settings",
)
STYLE = """
<style>
.block-container {padding-top:2.4rem; max-width:1500px;}
[data-testid="stSidebar"] {border-right:1px solid #24324A;}
h1 {font-size:2.1rem !important;letter-spacing:-.05rem;}
h2,h3 {letter-spacing:-.025rem;}
.kicker {color:#6EE7C0;letter-spacing:.17em;font-size:.73rem;font-weight:700;margin-bottom:.6rem;}
.subtle {color:#A7B5CB;font-size:.95rem;line-height:1.65;}
.hero {padding:1.6rem 1.8rem;border:1px solid #2B3D58;border-radius:16px;background:linear-gradient(115deg,#182B43,#111C30);margin:1rem 0 1.5rem;}
.hero h2 {font-size:1.6rem;margin:0 0 .4rem;}
.metric {padding:1.2rem;border:1px solid #29384F;border-radius:12px;background:#131E32;min-height:128px;}
.metric-label {color:#ACBBD0;font-size:.78rem;letter-spacing:.04em;}
.metric-value {font-size:1.8rem;font-weight:650;letter-spacing:-.04rem;margin:.4rem 0;}
.metric-note {color:#6EE7C0;font-size:.76rem;}
.board-card {border:1px solid #30415C;border-top:3px solid #6EE7C0;border-radius:10px;background:#162238;padding:1rem;margin:.7rem 0;min-height:170px;}
.board-card h4 {font-size:1rem;margin:0 0 .65rem;color:#F1F5F9;}
.board-card p {color:#B8C6DA;font-size:.85rem;margin:.35rem 0;}
.pill {display:inline-block;background:#243951;color:#BAEDD9;padding:.2rem .5rem;border-radius:5px;font-size:.7rem;}
[data-testid="stMetric"] {background:#131E32;border:1px solid #29384F;border-radius:12px;padding:1rem;}
[data-testid="stForm"] {border:1px solid #29384F;border-radius:12px;}
</style>
"""


def money(amount_cents, currency):
    return f"{currency} {amount_cents / 100:,.2f}"


def flash(message):
    st.session_state["flash"] = message
    st.rerun()


def chart(frame, x, y, title, kind="bar"):
    if frame.empty:
        st.info("No data yet. Add records to see this chart.")
        return
    fig = (px.line if kind == "line" else px.bar)(frame, x=x, y=y, title=title, color_discrete_sequence=["#6EE7C0"])
    if kind == "line":
        fig.update_traces(mode="lines+markers")
    fig.update_xaxes(type="category")
    fig.update_yaxes(rangemode="tozero")
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#CBD5E1"},
        margin={"l": 12, "r": 12, "t": 48, "b": 12},
        height=310,
        xaxis_title=None,
        yaxis_title=None,
    )
    st.plotly_chart(fig, use_container_width=True)


def display_table(rows, key):
    if not rows:
        st.info("No matching records. Create one below or adjust the filters.")
        return
    display = []
    for row in rows:
        formatted = {}
        for field, value in row.items():
            label = field.removesuffix("_cents").replace("_", " ").title()
            if field.endswith("_cents"):
                value = money(value, row["currency"]) if row.get("currency") else f"{value / 100:,.2f}"
            formatted[label] = value
        display.append(formatted)
    st.dataframe(pd.DataFrame(display), hide_index=True, use_container_width=True)
    st.download_button("Export these records · CSV", csv_export(rows), f"{key}.csv", "text/csv", key=f"export_{key}")


def enriched(service, table):
    rows = service.rows(table)
    clients = {r["id"]: r["name"] for r in service.rows("clients")}
    projects = {r["id"]: r["name"] for r in service.rows("projects")}
    for row in rows:
        if "client_id" in row:
            row["client"] = clients.get(row["client_id"], "")
        if "project_id" in row:
            row["project"] = projects.get(row["project_id"], "")
        if table == "projects":
            row["technology_stack"] = ", ".join(service.get(table, row["id"])["technology_stack"])
    return rows


def filtered(rows, table):
    with st.expander("Search, sort & filters", expanded=True):
        left, right = st.columns([3, 1])
        query = left.text_input(
            "Search", key=f"search_{table}", placeholder="Search names, notes, platforms…"
        ).casefold()
        order = right.selectbox(
            "Sort order", ("Newest first", "Oldest first", "Name A–Z", "Highest value"), key=f"order_{table}"
        )
        filter_fields = [
            k for k in ("platform", "technology_stack", "priority", "status", "currency") if any(k in r for r in rows)
        ]
        if filter_fields:
            cols = st.columns(len(filter_fields))
            for col, field in zip(cols, filter_fields):
                options = sorted({v.strip() for r in rows for v in str(r.get(field, "")).split(",") if v.strip()})
                chosen = col.multiselect(field.replace("_", " ").title(), options, key=f"filter_{table}_{field}")
                if chosen:
                    rows = [r for r in rows if set(chosen) & {v.strip() for v in str(r.get(field, "")).split(",")}]
        date_fields = [
            f
            for f in ("created_at", "deadline", "follow_up", "received_date", "due_date", "contact_date")
            if any(f in r for r in rows)
        ]
        if date_fields:
            cols = st.columns(3)
            field = cols[0].selectbox(
                "Date field", date_fields, format_func=lambda f: f.replace("_", " ").title(), key=f"date_field_{table}"
            )
            start = cols[1].date_input("From (optional)", value=None, key=f"from_{table}")
            end = cols[2].date_input("To (optional)", value=None, key=f"to_{table}")
            if start and end and start > end:
                st.warning("The start date must be on or before the end date.")
                rows = []
            elif start or end:
                rows = [
                    r
                    for r in rows
                    if r.get(field)
                    and (not start or r[field] >= start.isoformat())
                    and (not end or r[field] <= end.isoformat())
                ]
    if query:
        rows = [r for r in rows if query in " ".join(str(v) for v in r.values()).casefold()]
    value_key = next(
        (k for k in ("budget_cents", "estimated_cents", "amount_cents") if any(k in r for r in rows)), "id"
    )
    if order == "Name A–Z":
        return sorted(rows, key=lambda r: str(r.get("name", r.get("title", r.get("summary", "")))).casefold())
    return sorted(
        rows, key=lambda r: r.get(value_key if order == "Highest value" else "id", 0), reverse=order != "Oldest first"
    )


def editor(service, table, title):
    """One validated editor per entity. No SQL or persistence rules in form code."""
    with st.expander(title):
        records = service.rows(table)
        labels = {
            r[
                "id"
            ]: f"#{r['id']} · {r.get('name', r.get('title', r.get('summary', r.get('month', r.get('status', 'Record')))))}"
            for r in records
        }
        selection = st.selectbox(
            "Record",
            [None] + list(labels),
            format_func=lambda i: "＋ New record" if i is None else labels[i],
            key=f"choose_{table}",
        )
        row = service.get(table, selection) if selection is not None else {}
        prefix = f"{table}_{selection}_"
        data = {}
        stack = None

        def text(field, label=None, area=False):
            widget = st.text_area if area else st.text_input
            data[field] = widget(label or field.replace("_", " ").title(), value=row.get(field, ""), key=prefix + field)

        def choice(field, options, label=None):
            default = row.get(field, options[0] if options else None)
            data[field] = st.selectbox(
                label or field.replace("_", " ").title(),
                options,
                index=options.index(default) if default in options else 0,
                key=prefix + field,
            )

        def amount(field, label):
            data[field] = st.text_input(label, value=f"{row.get(field, 0) / 100:.2f}", key=prefix + field)

        def day(field, label=None, required=False):
            default = date.fromisoformat(row[field]) if row.get(field) else (date.today() if required else None)
            value = st.date_input(label or field.replace("_", " ").title(), value=default, key=prefix + field)
            data[field] = value.isoformat() if value else None

        def client_choice():
            clients = {r["id"]: r["name"] for r in service.rows("clients")}
            if not clients:
                st.info("Create a client first from the Clients page.")
                return False
            default = row.get("client_id", next(iter(clients)))
            options = list(clients)
            data["client_id"] = st.selectbox(
                "Client",
                options,
                index=options.index(default) if default in options else 0,
                format_func=lambda i: f"#{i} · {clients[i]}",
                key=prefix + "client_id",
            )
            return True

        # Relationship selectors must rerun outside the form when dependent options change.
        if table in ("projects", "proposals", "contact_history") and not client_choice():
            return
        if table == "payments":
            projects = {r["id"]: r for r in service.rows("projects")}
            if not projects:
                st.info("Create a project before recording payments.")
                return
            options = list(projects)
            default = row.get("project_id", options[0])
            data["project_id"] = st.selectbox(
                "Project",
                options,
                index=options.index(default) if default in options else 0,
                format_func=lambda i: f"#{i} · {projects[i]['name']} ({projects[i]['currency']})",
                key=prefix + "project_id",
            )
            data["currency"] = projects[data["project_id"]]["currency"]
            st.caption(f"Payment currency: {data['currency']} · inherited from the project")
        with st.form(prefix + "form"):
            if table == "clients":
                text("name", "Client name *")
                a, b = st.columns(2)
                with a:
                    text("email")
                with b:
                    text("company")
                text("notes", area=True)
            elif table == "projects":
                text("name", "Project name *")
                text("description", area=True)
                a, b, c = st.columns(3)
                with a:
                    text("platform")
                    data["platform"] = data["platform"].strip() or "Direct"
                    choice("currency", list(CURRENCIES))
                with b:
                    amount("budget_cents", "Budget")
                    amount("hourly_rate_cents", "Hourly rate / labor value")
                with c:
                    data["hours_worked"] = st.number_input(
                        "Hours worked",
                        min_value=0.0,
                        value=float(row.get("hours_worked", 0)),
                        step=0.5,
                        key=prefix + "hours",
                    )
                    day("deadline", "Deadline (optional)")
                stack = st.text_input(
                    "Technology stack (comma-separated)",
                    value=", ".join(row.get("technology_stack", [])),
                    key=prefix + "stack",
                ).split(",")
                a, b = st.columns(2)
                with a:
                    choice("priority", list(PRIORITIES))
                with b:
                    choice("status", list(PROJECT_STATUSES))
                text("next_action")
                text("notes", area=True)
            elif table == "proposals":
                text("title", "Opportunity / proposal title *")
                a, b = st.columns(2)
                with a:
                    choice("status", list(PROPOSAL_STATUSES))
                    text("platform")
                    data["platform"] = data["platform"].strip() or "Direct"
                with b:
                    choice("currency", list(CURRENCIES))
                    amount("estimated_cents", "Estimated revenue")
                day("follow_up", "Follow-up date (optional)")
                text("body", "Proposal content", area=True)
                st.caption("Copy a template from the Templates tab into the proposal content field.")
                templates = {r["id"]: r["name"] for r in service.rows("proposal_templates")}
                options = [None] + list(templates)
                default = row.get("template_id")
                data["template_id"] = st.selectbox(
                    "Template reference (optional)",
                    options,
                    index=options.index(default) if default in options else 0,
                    format_func=lambda i: "None" if i is None else templates[i],
                    key=prefix + "template",
                )
                text("next_action")
            elif table == "payments":
                amount("amount_cents", "Amount *")
                choice("status", ["Pending", "Received"])
                day("due_date", "Due date (optional)")
                day("received_date", "Received date (required for monthly revenue)")
                st.caption(
                    "For a pending payment, leave received date empty. An undated receipt is excluded from monthly goals."
                )
                text("notes", area=True)
            elif table == "contact_history":
                proposals = {
                    p["id"]: p["title"] for p in service.rows("proposals") if p["client_id"] == data["client_id"]
                }
                options = [None] + list(proposals)
                default = row.get("proposal_id")
                data["proposal_id"] = st.selectbox(
                    "Related proposal",
                    options,
                    index=options.index(default) if default in options else 0,
                    format_func=lambda i: "General client contact" if i is None else proposals[i],
                    key=prefix + "proposal",
                )
                day("contact_date", required=True)
                text("channel", "Channel * (email, call, platform…)")
                text("summary", "Contact summary *", area=True)
                text("next_action")
            elif table == "proposal_templates":
                text("name", "Template name *")
                text("body", "Template content *", area=True)
            submitted = st.form_submit_button("Save record", type="primary")
        if submitted:
            try:
                for field in data:
                    if field.endswith("_cents"):
                        data[field] = cents(data[field])
                service.save(table, data, selection, technology_stack=stack)
                flash("Record saved successfully.")
            except ValueError as exc:
                st.error(str(exc))
        if selection is not None:
            confirmed = st.checkbox("Confirm deletion of this record", key=prefix + "confirm_delete")
            if st.button("Delete record", disabled=not confirmed, key=prefix + "delete"):
                try:
                    service.delete(table, selection)
                    # Clear the selector before the record disappears from options.
                    st.session_state.pop(f"choose_{table}", None)
                    flash("Record deleted.")
                except ValueError as exc:
                    st.error(str(exc))


def overview(service, analytics, month, currency):
    summary = analytics.summary(month, currency)
    st.markdown('<div class="kicker">YOUR INDEPENDENT BUSINESS, IN FOCUS</div>', unsafe_allow_html=True)
    st.title("A clear view of your work.")
    st.caption(f"Freelance Management System v2.0 · {month} · {currency}")
    projects = service.rows("projects")
    active = sum(p["status"] == "In progress" for p in projects)
    proposals = service.rows("proposals")
    open_count = sum(p["status"] not in ("Accepted", "Rejected") for p in proposals)
    st.markdown(
        f'<div class="hero"><h2>Build great things. Keep business moving.</h2><div class="subtle">{active} active projects · {open_count} open opportunities · {len(service.rows("clients"))} client relationships<br>Track your next action, protect your focus, and understand what your work earns.</div></div>',
        unsafe_allow_html=True,
    )
    cards = [
        ("RECEIVED THIS MONTH", summary["monthly_received_cents"], "Dated receipts only"),
        ("PENDING PAYMENTS", summary["pending_cents"], "All outstanding invoices"),
        ("OPEN PIPELINE", summary["estimated_cents"], "Unweighted opportunities"),
        ("MONTHLY GOAL", summary["goal_cents"], "Configure in Settings"),
    ]
    for col, (label, amount, note) in zip(st.columns(4), cards):
        col.markdown(
            f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value">{money(amount, currency)}</div><div class="metric-note">{note}</div></div>',
            unsafe_allow_html=True,
        )
    st.write("")
    left, right = st.columns([2, 1])
    with left:
        chart(analytics.revenue(currency), "label", "revenue", f"Monthly receipts · {currency}", "line")
    with right:
        st.subheader("Your monthly target")
        progress = summary["goal_progress"]
        if progress is None:
            st.info("Set a monthly goal in Settings to track your progress.")
        else:
            st.metric("Goal reached", f"{progress:.1%}")
            st.progress(min(progress, 1.0))
            st.caption(
                f"{money(summary['monthly_received_cents'], currency)} of {money(summary['goal_cents'], currency)}"
            )
        conversion = summary["conversion_rate"]
        st.metric("Proposal conversion", f"{conversion:.0%}" if conversion is not None else "—")
        st.caption("Accepted ÷ decided proposals · selected currency · all time")
    if summary["undated_cents"]:
        st.warning(
            f"{money(summary['undated_cents'], currency)} in receipts have no payment date and are excluded from monthly charts and goals. Add dates in Financial analytics."
        )
    st.subheader("Next on your radar")
    actionable = [r for r in enriched(service, "projects") if r["status"] not in ("Completed", "Cancelled")]
    display_table(
        [{k: r[k] for k in ("name", "client", "status", "priority", "deadline", "next_action")} for r in actionable],
        "next_actions",
    )


def proposals_page(service):
    st.title("Proposal pipeline")
    st.caption("From the first signal to a signed engagement.")
    pipeline, templates = st.tabs(["Opportunities", "Templates"])
    with pipeline:
        rows = filtered(enriched(service, "proposals"), "proposals")
        for col, status in zip(st.columns(3), PROPOSAL_STATUSES[:3]):
            col.metric(status, sum(r["status"] == status for r in rows))
        for col, status in zip(st.columns(3), PROPOSAL_STATUSES[3:]):
            col.metric(status, sum(r["status"] == status for r in rows))
        display_table(rows, "proposals")
        editor(service, "proposals", "Create or edit a proposal")
    with templates:
        for template in service.rows("proposal_templates"):
            st.subheader(template["name"])
            st.code(template["body"], language=None)
        editor(service, "proposal_templates", "Create or edit a template")


def kanban(service):
    st.title("Kanban board")
    st.caption("A practical view of your delivery flow. Move work with the status control on each card.")
    rows = filtered(enriched(service, "projects"), "kanban")
    # Five columns remain readable on laptop screens; Streamlit stacks on narrow screens.
    for col, status in zip(st.columns(5), PROJECT_STATUSES):
        with col:
            selected = [r for r in rows if r["status"] == status]
            st.markdown(f"**{status}** · {len(selected)}")
            for row in selected:
                content = f'<div class="board-card"><h4>{escape(row["name"])}</h4><span class="pill">{escape(row["priority"])}</span><p>{escape(row["client"])}</p><p>{escape(money(row["budget_cents"], row["currency"]))}</p><p>{escape(row["next_action"] or "Set a next action")}</p></div>'
                st.markdown(content, unsafe_allow_html=True)
                new = st.selectbox(
                    "Move to", PROJECT_STATUSES, index=PROJECT_STATUSES.index(status), key=f"move_{row['id']}"
                )
                if new != status:
                    service.save("projects", {"status": new}, row["id"])
                    flash("Project moved.")


def financial(service, analytics, month, currency):
    st.title("Financial analytics")
    st.caption(f"{currency} only · selected month: {month}. No exchange-rate conversion or mixed-currency totals.")
    summary = analytics.summary(month, currency)
    for col, (label, key) in zip(
        st.columns(3),
        [
            ("Received this month", "monthly_received_cents"),
            ("Received · all time", "received_cents"),
            ("Pending · all dates", "pending_cents"),
        ],
    ):
        col.metric(label, money(summary[key], currency))
    st.caption("Pending amounts are recorded invoices; project budgets do not automatically create payments.")
    revenue_tab, payments_tab, profit_tab = st.tabs(["Revenue", "Payments", "Profitability"])
    with revenue_tab:
        chart(analytics.revenue(currency), "label", "revenue", f"Monthly received revenue · {currency}")
        a, b = st.columns(2)
        with a:
            chart(
                analytics.revenue(currency, "client"), "label", "revenue", f"Receipts by client · all time · {currency}"
            )
        with b:
            chart(
                analytics.revenue(currency, "platform"),
                "label",
                "revenue",
                f"Receipts by platform · all time · {currency}",
            )
        if summary["undated_cents"]:
            st.warning(
                f"Undated receipts: {money(summary['undated_cents'], currency)}. Excluded from monthly reports; included in all-time client and platform totals."
            )
    with payments_tab:
        display_table(
            filtered([r for r in enriched(service, "payments") if r["currency"] == currency], "payments"), "payments"
        )
        editor(service, "payments", "Record or edit a payment")
    with profit_tab:
        st.info(
            "Labor value = hours worked × hourly rate. Surplus = budget − labor value. This is a planning estimate before taxes, expenses and platform fees; it is not accounting net profit."
        )
        frame = analytics.profitability(currency)
        display_table(frame.to_dict("records"), "profitability")
        st.caption(
            f"All monetary values above are in {currency}. CSV monetary columns ending in _cents contain integer minor units."
        )


def settings(service, db, month, currency):
    st.title("Settings")
    st.caption("Goals, portable exports, and deliberate data management.")
    st.subheader("Monthly financial goal")
    summary = Analytics(db).summary(month, currency)
    with st.form("goal"):
        value = st.text_input(f"Goal for {month} · {currency}", value=f"{summary['goal_cents'] / 100:.2f}")
        if st.form_submit_button("Save goal", type="primary"):
            service.set_goal(month, currency, cents(value))
            flash("Monthly goal updated.")
    goals = service.rows("financial_goals")
    display_table(goals, "goals")
    if goals:
        goal_ids = [g["id"] for g in goals]
        goal = st.selectbox(
            "Goal to remove",
            goal_ids,
            format_func=lambda i: next(f"{g['month']} · {g['currency']}" for g in goals if g["id"] == i),
        )
        if st.button("Remove selected goal"):
            service.delete("financial_goals", goal)
            flash("Goal removed.")
    st.subheader("Export your workspace")
    st.caption("Exports may contain private information. Keep them outside version control.")
    st.download_button(
        "Download Excel workbook",
        excel_export(db),
        "freelance-workspace.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    table = st.selectbox("CSV entity", list(FIELDS))
    st.download_button("Download entity CSV", csv_export(service.rows(table)), f"{table}.csv", "text/csv")
    st.subheader("Backup & restore")
    if st.button("Prepare SQLite backup"):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "backup.sqlite3"
            backup_database(db.path, path)
            st.session_state["backup_bytes"] = path.read_bytes()
    if "backup_bytes" in st.session_state:
        st.download_button(
            "Download prepared backup",
            st.session_state["backup_bytes"],
            f"fms-{date.today()}.sqlite3",
            "application/octet-stream",
        )
        st.caption("This is a snapshot from when you clicked Prepare. Prepare again after changes.")
    upload = st.file_uploader("Restore a v2 SQLite backup to a new database", type=["sqlite3", "sqlite", "db"])
    if upload and st.button("Validate and restore to a new file"):
        destination = db.path.parent / f"restored-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.sqlite3"
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "upload.sqlite3"
            source.write_bytes(upload.getvalue())
            restore_database(source, destination)
        st.success(f"Restored to {destination}. The current database is preserved.")
        st.info("Stop Streamlit and restart with FMS_DB set to this new database path to use the restored workspace.")
    if st.button("Run database integrity checks"):
        from fms.storage import validate_backup

        validate_backup(db.path)
        st.success("Schema, SQLite integrity and foreign key checks passed.")
    st.subheader("Legacy migration & demonstration")
    st.caption(
        "Run these commands from the repository root. Each creates a new database and refuses an existing destination."
    )
    st.code(
        "python -m fms migrate --source freelancers.json --db data/migrated.sqlite3\npython -m fms demo --db data/demo.sqlite3",
        language="bash",
    )
    st.caption(
        "Set FMS_DB before launching to choose a workspace. The original CLI and its JSON file remain independent; there is no automatic sync."
    )


def run():
    st.set_page_config(page_title="Freelance Management System v2.0", page_icon="◈", layout="wide")
    st.markdown(STYLE, unsafe_allow_html=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    with st.sidebar:
        st.markdown('<div class="kicker">INDEPENDENT / ORGANIZED</div>', unsafe_allow_html=True)
        st.markdown("## Freelance\nWorkspace **v2.0**")
        st.caption("A place for your work to grow.")
        st.divider()
        page = st.radio("Workspace", PAGES, label_visibility="collapsed")
        st.divider()
        currency = st.selectbox("Analytics currency", CURRENCIES)
        selected_date = st.date_input("Reporting month", value=date.today().replace(day=1))
        month = selected_date.strftime("%Y-%m")
        st.caption("Local SQLite workspace · single user")
    try:
        path = Path(os.environ.get("FMS_DB", "data/freelance.sqlite3"))
        db = Database(path)
        db.initialize()
        service = Service(db)
        if message := st.session_state.pop("flash", None):
            st.success(message)
        if page == "Overview":
            overview(service, Analytics(db), month, currency)
        elif page in ("Clients", "Projects", "Contact history"):
            table = {"Clients": "clients", "Projects": "projects", "Contact history": "contact_history"}[page]
            st.title(page)
            st.caption(
                {
                    "clients": "Strong relationships start with a clear record.",
                    "projects": "Scope, delivery, and the next action — in one place.",
                    "contact_history": "Keep context from every conversation.",
                }[table]
            )
            display_table(filtered(enriched(service, table), table), table)
            if table == "projects":
                st.caption(
                    "Each project carries its own currency. CSV monetary columns ending in _cents contain integer minor units."
                )
            editor(service, table, f"Create or edit {'a contact' if table == 'contact_history' else 'a ' + table[:-1]}")
        elif page == "Proposal pipeline":
            proposals_page(service)
        elif page == "Kanban board":
            kanban(service)
        elif page == "Financial analytics":
            financial(service, Analytics(db), month, currency)
        else:
            settings(service, db, month, currency)
    except ValueError as exc:
        st.error(str(exc))
    except (sqlite3.Error, OSError) as exc:
        logging.getLogger(__name__).error("Storage operation failed: %s", type(exc).__name__)
        st.error(
            "The storage operation could not be completed. Check file access, available disk space and database integrity. Your source files have not been replaced."
        )
