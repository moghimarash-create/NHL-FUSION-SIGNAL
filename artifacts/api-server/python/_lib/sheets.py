"""Shared Google Sheets client. Reads service account JSON and NHL sheet IDs from env.
Includes a strict NBA spreadsheet blocklist so live NBA sheets can NEVER be modified."""
import json
import os
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

FORBIDDEN_NBA_SHEET_IDS = {
    "1YYAe9PqsxDLfMAMC5UyDz8Ihh3lLUz7UNwVUjWs5-fo",
    "1OOSLnGUdNiuSNSKzzkT6Q_UqI0dcj7J4AMkLwH4A24Q",
    "1Lasp4OwUsO3CZ86jzAXykJWTJll-mIDXRWtKQpIcntM",
    "1YVnrJxI8zVztJM9e5hGVBxRps4LblfxBFzAN7i20nqs",
    "1yi4rNBwT4iktcZms_lEJNJ-SPNQ9Kc0d-6AeX9KzikA",
    "1HSscf2X7yeE7_Wi74Svam9QcVZOVQqi25r5DhlyP5PQ",
    "1lFQgTDURItuY0LeIjcTeRRsAZDBHqXQ9j013qNq45o8",
    "1jw2UuFCyQLWCiPZimAmlCInu4Iq-ec149wyI6dJpK-U",
    "1CewQkD-FFuE6RAtAtosIvC2sLHmAywA4cCx1CSgVvHI",
    "1GCTMMwmOPpc6d3rVhY8_Tnr6lbJxiYqy62C3N2MUvBI",
    "1MqZL-5y7k5aQOYjfHdtnsRrBPviF811gnVGp8IggdtQ",
    "1sAszvBu7Ji83vsjuyN1dJXjpf2OTc1oAzIxYGEfv2-A",
}


def _load_service_account_info() -> dict[str, Any]:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON secret is not set. Using local JSON fallback."
        )
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON: {e}.") from e


_client: gspread.Client | None = None


def get_client() -> gspread.Client:
    global _client
    if _client is None:
        info = _load_service_account_info()
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        _client = gspread.authorize(creds)
    return _client


def open_sheet(spreadsheet_id: str) -> gspread.Spreadsheet:
    sid = str(spreadsheet_id or "").strip()
    if not sid:
        raise RuntimeError(
            "No NHL Google Sheet ID configured (set NHL_FUSION_INPUT_SHEET_ID / NHL_FUSION_CALC_SHEET_ID in .env)."
        )
    if sid in FORBIDDEN_NBA_SHEET_IDS:
        raise RuntimeError(f"Refusing to access protected live NBA Google Sheet ({sid}).")
    return get_client().open_by_key(sid)
