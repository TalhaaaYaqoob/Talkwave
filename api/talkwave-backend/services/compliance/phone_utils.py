"""Phone number utilities for compliance: E.164 normalization, hashing, and
region / timezone detection.

Uses the ``phonenumbers`` library when available and falls back to lightweight
heuristics so the module never hard-fails if the dependency is missing in a
given environment.
"""

import hashlib
from typing import List, Optional

from loguru import logger

try:
    import phonenumbers
    from phonenumbers import timezone as pn_timezone

    _HAS_PHONENUMBERS = True
except Exception:  # pragma: no cover - dependency optional at import time
    phonenumbers = None
    pn_timezone = None
    _HAS_PHONENUMBERS = False


# Map ISO country code -> compliance region used across the platform.
_COUNTRY_TO_REGION = {
    "US": "us",
    "CA": "us",  # North American Numbering Plan shares calling conventions
    "GB": "gb",
}


def normalize_e164(phone: str, default_region: str = "US") -> Optional[str]:
    """Normalize a phone number to E.164 (e.g. ``+14155550123``).

    Returns ``None`` if the number cannot be parsed.
    """
    if not phone:
        return None

    raw = phone.strip()

    if _HAS_PHONENUMBERS:
        try:
            parsed = phonenumbers.parse(raw, default_region)
            if phonenumbers.is_valid_number(parsed):
                return phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.E164
                )
            # Even if not "valid", attempt a best-effort format for possible numbers
            if phonenumbers.is_possible_number(parsed):
                return phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.E164
                )
        except Exception as e:
            logger.debug(f"phonenumbers failed to parse '{raw}': {e}")

    # Fallback: strip everything but digits and a leading +
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return None
    if raw.startswith("+"):
        return f"+{digits}"
    # Assume US/NANP if 10 or 11 digits
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return f"+{digits}"


def hash_phone(phone_e164: str) -> str:
    """SHA-256 hash of an E.164 number for privacy-preserving storage/lookup."""
    return hashlib.sha256(phone_e164.encode("utf-8")).hexdigest()


def normalize_and_hash(phone: str, default_region: str = "US") -> Optional[tuple]:
    """Return ``(e164, hash)`` tuple, or ``None`` if unparseable."""
    e164 = normalize_e164(phone, default_region)
    if not e164:
        return None
    return e164, hash_phone(e164)


def get_country_code(phone: str, default_region: str = "US") -> Optional[str]:
    """Return ISO-3166 alpha-2 country code for a number (e.g. ``US``, ``GB``)."""
    if _HAS_PHONENUMBERS:
        try:
            parsed = phonenumbers.parse(phone, default_region)
            region = phonenumbers.region_code_for_number(parsed)
            if region:
                return region
        except Exception:
            pass

    # Heuristic fallback based on country calling code
    e164 = normalize_e164(phone, default_region)
    if not e164:
        return None
    if e164.startswith("+1"):
        return "US"
    if e164.startswith("+44"):
        return "GB"
    return None


def get_compliance_region(phone: str, default_region: str = "US") -> str:
    """Map a phone number to a compliance region: ``us``, ``gb``, or ``other``."""
    country = get_country_code(phone, default_region)
    if not country:
        return "other"
    return _COUNTRY_TO_REGION.get(country, "other")


def get_timezones(phone: str, default_region: str = "US") -> List[str]:
    """Return a list of IANA timezones the number may be located in.

    Falls back to a sensible default per region when detection is unavailable.
    """
    if _HAS_PHONENUMBERS and pn_timezone is not None:
        try:
            parsed = phonenumbers.parse(phone, default_region)
            zones = list(pn_timezone.time_zones_for_number(parsed))
            if zones and zones != ["Etc/Unknown"]:
                return zones
        except Exception:
            pass

    region = get_compliance_region(phone, default_region)
    if region == "gb":
        return ["Europe/London"]
    # Default to US Eastern as the most conservative common default
    return ["America/New_York"]
