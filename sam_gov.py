"""Optional read-only integration with the official U.S. SAM.gov Entity API."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SAM_API_URL = "https://api.sam.gov/entity-information/v3/entities"


def lookup_entity(uei: str) -> dict:
    """Return a limited public registration summary for an explicitly supplied UEI."""
    key = os.environ.get("SAM_GOV_API_KEY", "").strip()
    if not key:
        return {"provider": "sam.gov", "status": "not_configured"}
    clean_uei = "".join(character for character in str(uei).upper() if character.isalnum())
    if len(clean_uei) != 12:
        return {"provider": "sam.gov", "status": "invalid_uei"}

    query = urlencode(
        {
            "api_key": key,
            "ueiSAM": clean_uei,
            "includeSections": "entityRegistration",
        }
    )
    request = Request(
        f"{SAM_API_URL}?{query}",
        headers={"Accept": "application/json", "User-Agent": "BIDVEIL/1.0"},
    )
    try:
        with urlopen(request, timeout=8) as response:
            body = json.loads(response.read(2_000_001).decode("utf-8"))
    except HTTPError as error:
        status = "unauthorized" if error.code in {401, 403} else "provider_error"
        return {"provider": "sam.gov", "status": status, "httpStatus": error.code}
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return {"provider": "sam.gov", "status": "unavailable"}

    records = body.get("entityData") if isinstance(body, dict) else None
    if not isinstance(records, list) or not records or not isinstance(records[0], dict):
        return {
            "provider": "sam.gov",
            "status": "not_found",
            "uei": clean_uei,
            "source": SAM_API_URL,
            "fetchedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }

    registration = records[0].get("entityRegistration") or {}
    if not isinstance(registration, dict):
        return {"provider": "sam.gov", "status": "provider_error", "source": SAM_API_URL}
    returned_uei = str(registration.get("ueiSAM") or "").upper()
    if returned_uei != clean_uei:
        return {
            "provider": "sam.gov",
            "status": "no_exact_match",
            "uei": clean_uei,
            "source": SAM_API_URL,
            "fetchedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
    return {
        "provider": "sam.gov",
        "status": "found",
        "uei": registration.get("ueiSAM") or clean_uei,
        "legalBusinessName": registration.get("legalBusinessName"),
        "registrationStatus": registration.get("registrationStatus"),
        "samRegistered": registration.get("samRegistered"),
        "ueiStatus": registration.get("ueiStatus"),
        "ueiExpirationDate": registration.get("ueiExpirationDate"),
        "source": SAM_API_URL,
        "fetchedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
