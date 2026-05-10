"""Pre-built market profiles for supported countries."""

from .australia import AUSTRALIA_PROFILE
from .canada import CANADA_PROFILE
from .germany import GERMANY_PROFILE
from .india import INDIA_PROFILE
from .japan import JAPAN_PROFILE
from .singapore import SINGAPORE_PROFILE
from .united_kingdom import UK_PROFILE
from .united_states import US_PROFILE

ALL_PROFILES = {
    "IN": INDIA_PROFILE,
    "US": US_PROFILE,
    "UK": UK_PROFILE,
    "AU": AUSTRALIA_PROFILE,
    "CA": CANADA_PROFILE,
    "DE": GERMANY_PROFILE,
    "JP": JAPAN_PROFILE,
    "SG": SINGAPORE_PROFILE,
}

__all__ = [
    "ALL_PROFILES",
    "AUSTRALIA_PROFILE",
    "CANADA_PROFILE",
    "GERMANY_PROFILE",
    "INDIA_PROFILE",
    "JAPAN_PROFILE",
    "SINGAPORE_PROFILE",
    "UK_PROFILE",
    "US_PROFILE",
]
