"""Unified station/site schema shared by every research infrastructure adapter.

The whole point of this repository is that ACTRIS, ICOS and eLTER describe the
same physical world with different fields.  Every adapter is therefore required
to emit exactly these columns, and nothing else, so that the differences between
the infrastructures become explicit data rather than implicit assumptions.
"""

from __future__ import annotations

import re
import unicodedata

# Canonical column order for the harmonised station table.
COLUMNS = [
    "ri",             # ACTRIS | ICOS | eLTER
    "source_id",      # identifier as issued by the RI (verbatim, never edited)
    "id_scheme",      # what KIND of identifier source_id is
    "uri",            # resolvable landing page / PID, if the RI provides one
    "name",           # station or site name, verbatim
    "name_norm",      # normalised name, used for fuzzy comparison only
    "lat",            # decimal degrees, WGS84
    "lon",            # decimal degrees, WGS84
    "elevation_m",    # metres above sea level, or NaN
    "country",        # ISO 3166-1 alpha-2, upper case, or ""
    "geometry_kind",  # point | centroid_of_polygon
    "station_class",  # RI-specific class label (AS/ES/OS, LTER site, ...)
    "extra_ids",      # JSON string: secondary identifiers (WIGOS, TC ids, ...)
]

# Tokens that carry no discriminative information when comparing names across
# infrastructures.  Kept deliberately small and auditable.
_STOPWORDS = {
    "station", "site", "observatory", "atmospheric", "atmosphere", "research",
    "ecosystem", "lter", "ltser", "platform", "the", "of", "de", "la", "el",
}

_PUNCT = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS = re.compile(r"\s+")


def normalise_name(name: str | None) -> str:
    """Fold a station name to a comparable form.

    Deliberately conservative: strip diacritics, lower-case, drop punctuation
    and a short stop-list, collapse whitespace.  Nothing is reordered and no
    abbreviation is expanded, because every such rule is a decision that would
    have to be documented in the data dictionary.
    """
    if not name:
        return ""
    folded = unicodedata.normalize("NFKD", str(name))
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = _PUNCT.sub(" ", folded.lower())
    tokens = [t for t in _WS.split(folded) if t and t not in _STOPWORDS]
    return " ".join(tokens)
