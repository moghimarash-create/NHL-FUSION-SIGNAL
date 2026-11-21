#!/usr/bin/env python3
"""
Canonical 32-Team NHL Normalizer, ESPN/Kalshi Code Mapper, and Astrological Team/Arena Metadata (DEG1 = 88).
Handles ESPN NHL abbreviations (LA/LAK, TB/TBL, NJ/NJD, SJ/SJS, UTA/UTAH, MTL, WSH, etc.),
Kalshi KXNHLGAME suffixes, Unicode accents (Montréal Canadiens), and historical relocations
(Utah Hockey Club / Arizona Coyotes / Phoenix Coyotes -> Utah Mammoth, Atlanta Thrashers -> Winnipeg Jets).
"""
import unicodedata

NHL_DEG1 = 88  # 28 GEMINI (AIR element)

EGEM_MAP = {
    'A': 1, 'B': 2, 'C': 20, 'D': 4, 'E': 5, 'F': 80, 'G': 3, 'H': 8, 'I': 10, 'J': 10,
    'K': 20, 'L': 30, 'M': 40, 'N': 50, 'O': 70, 'P': 80, 'Q': 100, 'R': 200, 'S': 60,
    'T': 400, 'U': 6, 'V': 6, 'W': 6, 'X': 70, 'Y': 10, 'Z': 7,
}

LETTER_EL = {}
for _ch in "EIJYOSUVW":
    LETTER_EL[_ch] = 0  # Fire
for _ch in "DGLQZ":
    LETTER_EL[_ch] = 1  # Air
for _ch in "ACKFPMNX":
    LETTER_EL[_ch] = 2  # Water
for _ch in "BHRT":
    LETTER_EL[_ch] = 3  # Earth


def clean_ascii(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(ch for ch in s if not unicodedata.combining(ch)).strip()


def egem(s: str) -> int:
    return sum(EGEM_MAP.get(ch, 0) for ch in clean_ascii(s).upper())


def word_fawe(s: str) -> list[int]:
    out = [0, 0, 0, 0]
    for ch in clean_ascii(s).upper():
        if ch in LETTER_EL:
            out[LETTER_EL[ch]] += 1
    return out


NHL_TEAMS_32 = [
    "Anaheim Ducks",
    "Boston Bruins",
    "Buffalo Sabres",
    "Calgary Flames",
    "Carolina Hurricanes",
    "Chicago Blackhawks",
    "Colorado Avalanche",
    "Columbus Blue Jackets",
    "Dallas Stars",
    "Detroit Red Wings",
    "Edmonton Oilers",
    "Florida Panthers",
    "Los Angeles Kings",
    "Minnesota Wild",
    "Montreal Canadiens",
    "Nashville Predators",
    "New Jersey Devils",
    "New York Islanders",
    "New York Rangers",
    "Ottawa Senators",
    "Philadelphia Flyers",
    "Pittsburgh Penguins",
    "San Jose Sharks",
    "Seattle Kraken",
    "St. Louis Blues",
    "Tampa Bay Lightning",
    "Toronto Maple Leafs",
    "Utah Mammoth",
    "Vancouver Canucks",
    "Vegas Golden Knights",
    "Washington Capitals",
    "Winnipeg Jets",
]

# (canonical_name, std_3letter_code, kalshi_code, home_arena, iana_tz)
_RAW_NHL_32 = [
    ("Anaheim Ducks",         "ANA", "ANA", "Honda Center",                  "America/Los_Angeles"),
    ("Boston Bruins",         "BOS", "BOS", "TD Garden",                     "America/New_York"),
    ("Buffalo Sabres",        "BUF", "BUF", "KeyBank Center",                "America/New_York"),
    ("Calgary Flames",        "CGY", "CGY", "Scotiabank Saddledome",         "America/Edmonton"),
    ("Carolina Hurricanes",   "CAR", "CAR", "Lenovo Center",                 "America/New_York"),
    ("Chicago Blackhawks",    "CHI", "CHI", "United Center",                 "America/Chicago"),
    ("Colorado Avalanche",    "COL", "COL", "Ball Arena",                    "America/Denver"),
    ("Columbus Blue Jackets", "CBJ", "CBJ", "Nationwide Arena",              "America/New_York"),
    ("Dallas Stars",          "DAL", "DAL", "American Airlines Center",      "America/Chicago"),
    ("Detroit Red Wings",     "DET", "DET", "Little Caesars Arena",          "America/Detroit"),
    ("Edmonton Oilers",       "EDM", "EDM", "Rogers Place",                  "America/Edmonton"),
    ("Florida Panthers",      "FLA", "FLA", "Amerant Bank Arena",            "America/New_York"),
    ("Los Angeles Kings",     "LAK", "LA",  "Crypto.com Arena",              "America/Los_Angeles"),
    ("Minnesota Wild",        "MIN", "MIN", "Grand Casino Arena",            "America/Chicago"),
    ("Montreal Canadiens",    "MTL", "MTL", "Centre Bell",                   "America/Toronto"),
    ("Nashville Predators",   "NSH", "NSH", "Bridgestone Arena",             "America/Chicago"),
    ("New Jersey Devils",     "NJD", "NJ",  "Prudential Center",             "America/New_York"),
    ("New York Islanders",    "NYI", "NYI", "UBS Arena",                     "America/New_York"),
    ("New York Rangers",      "NYR", "NYR", "Madison Square Garden",         "America/New_York"),
    ("Ottawa Senators",       "OTT", "OTT", "Canadian Tire Centre",          "America/Toronto"),
    ("Philadelphia Flyers",   "PHI", "PHI", "Xfinity Mobile Arena",          "America/New_York"),
    ("Pittsburgh Penguins",   "PIT", "PIT", "PPG Paints Arena",              "America/New_York"),
    ("San Jose Sharks",       "SJS", "SJ",  "SAP Center at San Jose",        "America/Los_Angeles"),
    ("Seattle Kraken",        "SEA", "SEA", "Climate Pledge Arena",          "America/Los_Angeles"),
    ("St. Louis Blues",       "STL", "STL", "Enterprise Center",             "America/Chicago"),
    ("Tampa Bay Lightning",   "TBL", "TB",  "Benchmark International Arena", "America/New_York"),
    ("Toronto Maple Leafs",   "TOR", "TOR", "Scotiabank Arena",              "America/Toronto"),
    ("Utah Mammoth",          "UTA", "UTA", "Delta Center",                  "America/Denver"),
    ("Vancouver Canucks",     "VAN", "VAN", "Rogers Arena",                  "America/Vancouver"),
    ("Vegas Golden Knights",  "VGK", "VGK", "T-Mobile Arena",                "America/Los_Angeles"),
    ("Washington Capitals",   "WSH", "WSH", "Capital One Arena",             "America/New_York"),
    ("Winnipeg Jets",         "WPG", "WPG", "Canada Life Centre",            "America/Winnipeg"),
]

TEAM_META_32 = {}
TEAM_TO_CODE = {}
TEAM_TO_KALSHI = {}
TEAM_TO_TZ = {}
TEAM_TO_ARENA = {}

for _name, _code, _kcode, _arena, _tz in _RAW_NHL_32:
    TEAM_META_32[_name] = {
        "deg1": NHL_DEG1,
        "deg2": egem(_name) % 360,
        "deg3": egem(_arena) % 360,
        "code_deg2": egem(_code) % 360,
        "tz": _tz,
        "arena": _arena,
        "lat": "",
        "lon": "",
        "code": _code,
        "kalshi": _kcode,
        "fawe": tuple(word_fawe(_name)),
    }
    TEAM_TO_CODE[_name] = _code
    TEAM_TO_KALSHI[_name] = _kcode
    TEAM_TO_TZ[_name] = _tz
    TEAM_TO_ARENA[_name] = _arena

# Hydrate canonical TEM-GEM(DEG2), SUM-CITY-ARENA(DEG3), LAT/LON, and TZ from nhl_gem_sheet.json
import json as _json
import os as _os

_GEM_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "nhl_gem_sheet.json")
if _os.path.exists(_GEM_PATH):
    try:
        _gem_rows = _json.load(open(_GEM_PATH, "r", encoding="utf-8")).get("values", [])
        for _r in _gem_rows[1:]:
            if not _r or not str(_r[0]).strip():
                continue
            _tn = str(_r[0]).strip()
            if _tn in TEAM_META_32:
                TEAM_META_32[_tn]["deg2"] = int(float(_r[3])) % 360
                TEAM_META_32[_tn]["deg3"] = int(float(_r[13])) % 360
                if len(_r) > 24 and str(_r[24]).strip():
                    TEAM_META_32[_tn]["code_deg2"] = int(float(_r[24])) % 360
                if len(_r) > 7 and str(_r[7]).strip():
                    TEAM_META_32[_tn]["arena"] = str(_r[7]).strip()
                    TEAM_TO_ARENA[_tn] = TEAM_META_32[_tn]["arena"]
                if len(_r) > 21:
                    TEAM_META_32[_tn]["lat"] = str(_r[21]).strip()
                if len(_r) > 22:
                    TEAM_META_32[_tn]["lon"] = str(_r[22]).strip()
                if len(_r) > 23 and str(_r[23]).strip():
                    TEAM_META_32[_tn]["tz"] = str(_r[23]).strip()
                    TEAM_TO_TZ[_tn] = TEAM_META_32[_tn]["tz"]
    except Exception:
        pass

# Also register Utah Hockey Club metadata directly for backward compatibility if ever looked up raw
TEAM_META_32["Utah Hockey Club"] = dict(TEAM_META_32["Utah Mammoth"])

ESPN_ABBR_TO_CANON = {
    "ANA":  ("Anaheim Ducks", "ANA"),
    "BOS":  ("Boston Bruins", "BOS"),
    "BUF":  ("Buffalo Sabres", "BUF"),
    "CGY":  ("Calgary Flames", "CGY"),
    "CAL":  ("Calgary Flames", "CGY"),
    "CAR":  ("Carolina Hurricanes", "CAR"),
    "CHI":  ("Chicago Blackhawks", "CHI"),
    "COL":  ("Colorado Avalanche", "COL"),
    "CBJ":  ("Columbus Blue Jackets", "CBJ"),
    "CLB":  ("Columbus Blue Jackets", "CBJ"),
    "DAL":  ("Dallas Stars", "DAL"),
    "DET":  ("Detroit Red Wings", "DET"),
    "EDM":  ("Edmonton Oilers", "EDM"),
    "FLA":  ("Florida Panthers", "FLA"),
    "LA":   ("Los Angeles Kings", "LAK"),
    "LAK":  ("Los Angeles Kings", "LAK"),
    "MIN":  ("Minnesota Wild", "MIN"),
    "MTL":  ("Montreal Canadiens", "MTL"),
    "MON":  ("Montreal Canadiens", "MTL"),
    "NSH":  ("Nashville Predators", "NSH"),
    "NAS":  ("Nashville Predators", "NSH"),
    "NJ":   ("New Jersey Devils", "NJD"),
    "NJD":  ("New Jersey Devils", "NJD"),
    "NYI":  ("New York Islanders", "NYI"),
    "NYR":  ("New York Rangers", "NYR"),
    "OTT":  ("Ottawa Senators", "OTT"),
    "PHI":  ("Philadelphia Flyers", "PHI"),
    "PIT":  ("Pittsburgh Penguins", "PIT"),
    "SJ":   ("San Jose Sharks", "SJS"),
    "SJS":  ("San Jose Sharks", "SJS"),
    "SEA":  ("Seattle Kraken", "SEA"),
    "STL":  ("St. Louis Blues", "STL"),
    "TB":   ("Tampa Bay Lightning", "TBL"),
    "TBL":  ("Tampa Bay Lightning", "TBL"),
    "TOR":  ("Toronto Maple Leafs", "TOR"),
    "UTA":  ("Utah Mammoth", "UTA"),
    "UTAH": ("Utah Mammoth", "UTA"),
    "ARI":  ("Utah Mammoth", "UTA"),
    "PHX":  ("Utah Mammoth", "UTA"),
    "VAN":  ("Vancouver Canucks", "VAN"),
    "VGK":  ("Vegas Golden Knights", "VGK"),
    "VEG":  ("Vegas Golden Knights", "VGK"),
    "LV":   ("Vegas Golden Knights", "VGK"),
    "WSH":  ("Washington Capitals", "WSH"),
    "WAS":  ("Washington Capitals", "WSH"),
    "WPG":  ("Winnipeg Jets", "WPG"),
    "ATL":  ("Winnipeg Jets", "WPG"),
}

HIST_TEAM_NORM = {
    "Montreal Canadiens": "Montreal Canadiens",
    "Montréal Canadiens": "Montreal Canadiens",
    "St Louis Blues": "St. Louis Blues",
    "St. Louis Blues": "St. Louis Blues",
    "LA Kings": "Los Angeles Kings",
    "Utah Hockey Club": "Utah Mammoth",
    "Utah Mammoth": "Utah Mammoth",
    "Arizona Coyotes": "Utah Mammoth",
    "Phoenix Coyotes": "Utah Mammoth",
    "Atlanta Thrashers": "Winnipeg Jets",
}

_LOWER_NAME_MAP = {k.lower(): v for k, v in HIST_TEAM_NORM.items()}
for _nm in NHL_TEAMS_32:
    _LOWER_NAME_MAP[_nm.lower()] = _nm


def norm_team(name: str) -> str:
    raw = clean_ascii(str(name or "")).strip()
    if not raw:
        return ""
    up = raw.upper()
    if up in ESPN_ABBR_TO_CANON:
        return ESPN_ABBR_TO_CANON[up][0]
    low = raw.lower()
    if low in _LOWER_NAME_MAP:
        return _LOWER_NAME_MAP[low]
    return HIST_TEAM_NORM.get(raw, raw)


def get_kalshi_code(team_or_code: str) -> str:
    raw = clean_ascii(str(team_or_code or "")).strip()
    if not raw:
        return ""
    canon = norm_team(raw)
    if canon in TEAM_TO_KALSHI:
        return TEAM_TO_KALSHI[canon]
    up = raw.upper()
    if up in {"LA", "LAK"}:
        return "LA"
    if up in {"NJ", "NJD"}:
        return "NJ"
    if up in {"SJ", "SJS"}:
        return "SJ"
    if up in {"TB", "TBL"}:
        return "TB"
    if up in {"UTA", "UTAH", "ARI", "PHX"}:
        return "UTA"
    if up in {"WSH", "WAS"}:
        return "WSH"
    return up[:3]


def season_of_date(d_iso: str) -> str:
    if "2019-10-01" <= d_iso <= "2020-10-05":
        return "2019-20"
    if "2020-10-06" <= d_iso <= "2021-08-15":
        return "2020-21"
    y, m, _ = map(int, str(d_iso).split("-"))
    return f"{y}-{(y + 1) % 100:02d}" if m >= 9 else f"{y - 1}-{y % 100:02d}"
