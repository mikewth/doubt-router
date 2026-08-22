"""
Thin wrapper around notion-client for the three databases we use.
"""
import os
from datetime import datetime, timezone
from notion_client import Client

notion = Client(auth=os.environ["NOTION_TOKEN"])

REQUESTS_DB = os.environ["NOTION_REQUESTS_DB_ID"]
RUNLOG_DB = os.environ["NOTION_RUNLOG_DB_ID"]
BLACKLIST_DB = os.environ["NOTION_BLACKLIST_DB_ID"]
ANSWERER_POOL_DB = os.environ["NOTION_ANSWERER_POOL_DB_ID"]


def get_latest_request_for_user(username: str):
    """For the /status command — most recent request submitted by this username."""
    results = notion.databases.query(
        database_id=REQUESTS_DB,
        filter={"property": "Telegram Username", "rich_text": {"equals": username}},
        sorts=[{"timestamp": "created_time", "direction": "descending"}],
        page_size=1,
    )
    return results["results"][0] if results["results"] else None


def get_answerer_pool() -> list[dict]:
    """Returns [{'username': ..., 'subjects': [...]}] for the AI prompt."""
    results = notion.databases.query(database_id=ANSWERER_POOL_DB)
    pool = []
    for page in results["results"]:
        username = get_page_text(page, "Telegram Username")
        subjects_prop = page["properties"].get("Subjects", {})
        subjects = [s["name"] for s in subjects_prop.get("multi_select", [])]
        if username:
            pool.append({"username": username, "subjects": subjects})
    return pool


def create_request(name: str, telegram_username: str, chat_id: str, raw_text: str) -> str:
    """Creates a new Requests row directly (used when Telegram is the intake
    trigger, instead of waiting for a form submission). Returns the new page id."""
    page = notion.pages.create(
        parent={"database_id": REQUESTS_DB},
        properties={
            "Name": {"title": [{"text": {"content": name or telegram_username}}]},
            "Telegram Username": {"rich_text": [{"text": {"content": telegram_username}}]},
            "Chat ID": {"rich_text": [{"text": {"content": str(chat_id)}}]},
            "Raw Text": {"rich_text": [{"text": {"content": raw_text}}]},
            "Status": {"select": {"name": "Processing"}},
        },
    )
    return page["id"]


def get_new_requests():
    """Requests submitted via the Notion Form that haven't been AI-processed yet
    (Subject field still empty)."""
    results = notion.databases.query(
        database_id=REQUESTS_DB,
        filter={"property": "Subject", "rich_text": {"is_empty": True}},
    )
    return results["results"]


def get_approved_requests():
    """Requests a human has approved but that haven't been sent yet."""
    results = notion.databases.query(
        database_id=REQUESTS_DB,
        filter={"property": "Status", "select": {"equals": "Approved"}},
    )
    return results["results"]


def update_request(page_id: str, subject: str = None, priority: str = None,
                    status: str = None, assigned_to: str = None):
    """Write AI-parsed fields and/or a new status back to a Requests row."""
    properties = {}
    if subject is not None:
        properties["Subject"] = {"rich_text": [{"text": {"content": subject}}]}
    if priority is not None:
        properties["Priority"] = {"select": {"name": priority}}
    if status is not None:
        properties["Status"] = {"select": {"name": status}}
    if assigned_to is not None:
        properties["Assigned To"] = {"rich_text": [{"text": {"content": assigned_to}}]}
    notion.pages.update(page_id=page_id, properties=properties)


def get_answer(page: dict) -> str:
    """Reads the answerer's typed reply from the Answer field."""
    return get_page_text(page, "Answer")


def get_page_text(page: dict, field: str) -> str:
    """Pull plain text out of a Notion rich_text/title property."""
    prop = page["properties"].get(field, {})
    kind = prop.get("type")
    parts = prop.get(kind, [])
    return "".join(p.get("plain_text", "") for p in parts)


def get_page_select(page: dict, field: str) -> str:
    """Pull the selected option name out of a Notion select property."""
    prop = page["properties"].get(field, {})
    selected = prop.get("select")
    return selected["name"] if selected else ""


def is_blacklisted(username: str) -> bool:
    results = notion.databases.query(
        database_id=BLACKLIST_DB,
        filter={"property": "Username", "title": {"equals": username}},
    )
    return len(results["results"]) > 0


def write_run_log(action: str, result: str):
    notion.pages.create(
        parent={"database_id": RUNLOG_DB},
        properties={
            "Timestamp": {"date": {"start": datetime.now(timezone.utc).isoformat()}},
            "Action": {"rich_text": [{"text": {"content": action}}]},
            "Result": {"rich_text": [{"text": {"content": result}}]},
        },
    )
