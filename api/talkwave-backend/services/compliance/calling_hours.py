"""TCPA calling-hours enforcement based on the recipient's local time.

TCPA restricts telemarketing calls to 8:00 AM - 9:00 PM in the *called party's*
local time. UK PECR has no statutory hours but 8am-9pm is best practice, so we
apply the same window for ``gb``.
"""

from datetime import datetime, time
from typing import Tuple
from zoneinfo import ZoneInfo

from loguru import logger

from api.services.compliance.phone_utils import (
    get_compliance_region,
    get_timezones,
)

# Default permitted window (local time of the recipient).
DEFAULT_START = time(8, 0)
DEFAULT_END = time(21, 0)


def is_within_permitted_hours(
    phone: str,
    start: time = DEFAULT_START,
    end: time = DEFAULT_END,
    default_region: str = "US",
) -> Tuple[bool, str]:
    """Return ``(allowed, reason)`` for calling ``phone`` right now.

    Evaluates the recipient's local time across all timezones the number may
    belong to. The call is permitted only if the current moment is within the
    window in *every* candidate timezone (conservative for multi-zone numbers).
    """
    zones = get_timezones(phone, default_region)
    if not zones:
        # No timezone info — fall back to permitting (gate still checks DNC/consent)
        return True, "no_timezone_info"

    for zone_name in zones:
        try:
            tz = ZoneInfo(zone_name)
        except Exception:
            logger.debug(f"Unknown timezone '{zone_name}' for {phone}")
            continue

        now_local = datetime.now(tz).time()
        if not (start <= now_local <= end):
            return (
                False,
                f"outside_hours_{zone_name}_{now_local.strftime('%H:%M')}",
            )

    region = get_compliance_region(phone, default_region)
    return True, f"within_hours_{region}"
