"""GoCardless Bank Account Data API client (formerly Nordigen)."""
import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://bankaccountdata.gocardless.com/api/v2"

SECRET_ID = os.getenv("GOCARDLESS_SECRET_ID", "")
SECRET_KEY = os.getenv("GOCARDLESS_SECRET_KEY", "")

# ── Module-level token state ──────────────────────────────────────────────────

_access_token: str | None = None
_access_expires_at: datetime | None = None
_refresh_token: str | None = None
_refresh_expires_at: datetime | None = None


def is_configured() -> bool:
    """Return True if GoCardless credentials are set in environment."""
    return bool(SECRET_ID and SECRET_KEY)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_expires(seconds: int) -> datetime:
    from datetime import timedelta
    return _utcnow() + timedelta(seconds=seconds)


def _fetch_new_token() -> None:
    """Fetch a brand-new access+refresh token pair from GoCardless."""
    global _access_token, _access_expires_at, _refresh_token, _refresh_expires_at

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{BASE_URL}/token/new/",
            json={"secret_id": SECRET_ID, "secret_key": SECRET_KEY},
        )
        resp.raise_for_status()
        data = resp.json()

    _access_token = data["access"]
    _access_expires_at = _parse_expires(data.get("access_expires", 86400))
    _refresh_token = data["refresh"]
    _refresh_expires_at = _parse_expires(data.get("refresh_expires", 2592000))
    logger.debug("GoCardless: fetched new token pair")


def _refresh_access_token() -> None:
    """Use the refresh token to get a new access token."""
    global _access_token, _access_expires_at

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{BASE_URL}/token/refresh/",
            json={"refresh": _refresh_token},
        )
        resp.raise_for_status()
        data = resp.json()

    _access_token = data["access"]
    _access_expires_at = _parse_expires(data.get("access_expires", 86400))
    logger.debug("GoCardless: refreshed access token")


def _get_auth_headers() -> dict:
    """Return Authorization headers, refreshing or fetching tokens as needed."""
    from datetime import timedelta

    buffer = timedelta(seconds=300)  # 5-minute buffer
    now = _utcnow()

    if _access_token and _access_expires_at and (_access_expires_at - now) > buffer:
        # Access token still valid
        return {"Authorization": f"Bearer {_access_token}"}

    if _refresh_token and _refresh_expires_at and (_refresh_expires_at - now) > buffer:
        # Access expired but refresh still valid
        try:
            _refresh_access_token()
            return {"Authorization": f"Bearer {_access_token}"}
        except Exception as exc:
            logger.warning("GoCardless: refresh failed (%s), fetching new pair", exc)

    # No valid tokens — fetch fresh pair
    _fetch_new_token()
    return {"Authorization": f"Bearer {_access_token}"}


# ── Public API functions ──────────────────────────────────────────────────────

def get_institutions(country: str = "BE") -> list[dict]:
    """Return list of institutions for the given country."""
    headers = _get_auth_headers()
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"{BASE_URL}/institutions/",
            params={"country": country},
            headers=headers,
        )
        resp.raise_for_status()
    return resp.json()


def create_requisition(institution_id: str, redirect_url: str, reference: str) -> dict:
    """Create a GoCardless requisition (bank link request).

    Returns the full response dict including ``link`` (authorization URL)
    and ``id`` (requisition UUID).
    """
    headers = _get_auth_headers()
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{BASE_URL}/requisitions/",
            json={
                "redirect": redirect_url,
                "institution_id": institution_id,
                "reference": reference,
                "user_language": "FR",
            },
            headers=headers,
        )
        resp.raise_for_status()
    return resp.json()


def get_requisition(requisition_id: str) -> dict:
    """Fetch requisition details (status, accounts list)."""
    headers = _get_auth_headers()
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"{BASE_URL}/requisitions/{requisition_id}/",
            headers=headers,
        )
        resp.raise_for_status()
    return resp.json()


def get_account_details(account_id: str) -> dict:
    """Fetch account details (iban, ownerName, name, currency)."""
    headers = _get_auth_headers()
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"{BASE_URL}/accounts/{account_id}/details/",
            headers=headers,
        )
        resp.raise_for_status()
    data = resp.json()
    # GoCardless wraps in {"account": {...}}
    return data.get("account", data)


def get_account_balances(account_id: str) -> list[dict]:
    """Fetch account balances list."""
    headers = _get_auth_headers()
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"{BASE_URL}/accounts/{account_id}/balances/",
            headers=headers,
        )
        resp.raise_for_status()
    data = resp.json()
    # GoCardless wraps in {"balances": [...]}
    return data.get("balances", data if isinstance(data, list) else [])


def delete_requisition(requisition_id: str) -> None:
    """Delete a requisition from GoCardless."""
    headers = _get_auth_headers()
    with httpx.Client(timeout=30) as client:
        resp = client.delete(
            f"{BASE_URL}/requisitions/{requisition_id}/",
            headers=headers,
        )
        # 404 is acceptable (already deleted)
        if resp.status_code != 404:
            resp.raise_for_status()


def pick_best_balance(balances: list[dict]) -> tuple[float, str]:
    """Pick the most relevant balance from a GoCardless balances list.

    Priority: closingBooked > interimAvailable > openingBooked.
    Returns (amount_float, currency).
    """
    priority = ["closingBooked", "interimAvailable", "openingBooked"]

    by_type: dict[str, dict] = {}
    for b in balances:
        bt = b.get("balanceType", "")
        by_type[bt] = b

    for btype in priority:
        if btype in by_type:
            bal = by_type[btype]
            amt_obj = bal.get("balanceAmount", {})
            try:
                amount = float(amt_obj.get("amount", 0))
            except (TypeError, ValueError):
                amount = 0.0
            currency = amt_obj.get("currency", "EUR")
            return amount, currency

    # Fallback: first balance in list
    if balances:
        amt_obj = balances[0].get("balanceAmount", {})
        try:
            amount = float(amt_obj.get("amount", 0))
        except (TypeError, ValueError):
            amount = 0.0
        currency = amt_obj.get("currency", "EUR")
        return amount, currency

    return 0.0, "EUR"
