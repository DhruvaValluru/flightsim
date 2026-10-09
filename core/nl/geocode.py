"""Place words to coordinates: "over New York" becomes a latitude/longitude.

The curated bakes (core/terrain/glo30.py LOCATIONS, the compiler's
PLACE_WORDS) remain the first answer for the places they name. Everything
else a prompt names goes through this module, in a fixed order:

1. **The built-in list** (:data:`GAZETTEER`): cities, airports, peaks and
   landmarks, each with an approximate ground elevation. Instant, works
   with no network, and always gives the same answer.
2. **OpenStreetMap Nominatim** (``nominatim.openstreetmap.org``, free, no
   key) for anything the list lacks. One query per compile at most,
   spaced at least a second apart (the service's usage policy), and every
   answer -- found or not -- is cached in ``data/geocode_cache.json`` so
   the same words give the same place on every later compile.

What is and is not claimed
--------------------------
* The coordinates are the place's centre as the list or OpenStreetMap
  states it. The terrain bake that follows is the usual on-demand GLO-30
  bake (about 27 x 20 km around the point), with every check that path
  runs.
* The list's ``elevation_m`` is an approximate ground height at that
  point (city centre, airfield, or summit for a peak). It sets the
  spec's terrain datum so the altitude check and the altitude guide work
  before the bake exists; the bake's raster is the physics ground.
  OpenStreetMap results carry no elevation, so the datum is left as it
  was.
* A word is only read as a place after a location word ("over", "near",
  "above", "in", ...), so "a Boston terrier" is not Boston, and an
  OpenStreetMap answer is only accepted for a geographic kind of result
  (a settlement, boundary, natural feature, airport or landmark) above a
  minimum importance -- "in heavy turbulence" never becomes a village.

Modes (``FLIGHTSIM_GEOCODER``)
------------------------------
``auto`` (default) uses the list then OpenStreetMap; ``offline`` uses the
list only (the test suite runs this way, so no test touches the network);
``off`` disables place lookup entirely.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

GEOCODER_ENV = "FLIGHTSIM_GEOCODER"
CACHE_ENV = "FLIGHTSIM_GEOCODE_CACHE"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
#: The usage policy asks for an identifying User-Agent and at most one
#: request per second.
USER_AGENT = "flightsim/1.0 (+https://github.com/dhruvavalluru/flightsim)"
MIN_REQUEST_INTERVAL_S = 1.0
REQUEST_TIMEOUT_S = 8.0
#: Below this Nominatim "importance" a hit is too obscure to trust from
#: free text (a hamlet that happens to share a word with the prompt).
MIN_IMPORTANCE = 0.3
#: Nominatim result categories that are places one can fly over.
ACCEPTED_CATEGORIES = frozenset({
    "place", "boundary", "natural", "aeroway", "tourism", "historic",
    "leisure", "waterway", "man_made", "landuse", "mountain_pass",
})

SOURCE_LIST = "built-in place list"
SOURCE_OSM = "OpenStreetMap Nominatim"

_REPO = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = _REPO / "data" / "geocode_cache.json"


@dataclass(frozen=True)
class Place:
    """One resolved place."""

    name: str
    latitude: float
    longitude: float
    #: Approximate ground elevation (m MSL) at the point, or None.
    elevation_m: Optional[float]
    #: The words in the prompt that named it.
    phrase: str
    #: SOURCE_LIST or SOURCE_OSM.
    source: str
    #: What the source calls it ("New York, United States").
    display: str

    def describe(self) -> str:
        return f"{self.phrase!r}: {self.display} ({self.source})"


# -- the built-in list -------------------------------------------------------

#: (name, latitude, longitude, approx. ground elevation m MSL, country,
#: other names). Elevations are city-centre / airfield / summit heights,
#: rounded; a peak's entry IS its summit, so a flight "over" it is planned
#: above the top.
GAZETTEER: Tuple[Tuple[str, float, float, float, str, Tuple[str, ...]], ...] = (
    # United States
    ("New York City", 40.7128, -74.0060, 10, "United States",
     ("new york", "nyc", "manhattan")),
    ("Brooklyn", 40.6782, -73.9442, 20, "United States", ()),
    ("Central Park", 40.7829, -73.9654, 40, "United States", ()),
    ("Statue of Liberty", 40.6892, -74.0445, 2, "United States", ()),
    ("Empire State Building", 40.7484, -73.9857, 20, "United States", ()),
    ("JFK Airport", 40.6413, -73.7781, 4, "United States",
     ("jfk", "kennedy airport")),
    ("LaGuardia Airport", 40.7769, -73.8740, 6, "United States",
     ("laguardia",)),
    ("Los Angeles", 34.0522, -118.2437, 93, "United States", ()),
    ("Hollywood", 34.0928, -118.3287, 100, "United States", ()),
    ("Los Angeles Airport", 33.9416, -118.4085, 38, "United States",
     ("lax airport",)),
    ("Chicago", 41.8781, -87.6298, 181, "United States", ()),
    ("O'Hare Airport", 41.9742, -87.9073, 204, "United States",
     ("o'hare", "ohare")),
    ("Houston", 29.7604, -95.3698, 15, "United States", ()),
    ("Phoenix", 33.4484, -112.0740, 331, "United States", ()),
    ("Philadelphia", 39.9526, -75.1652, 12, "United States", ()),
    ("San Antonio", 29.4241, -98.4936, 198, "United States", ()),
    ("San Diego", 32.7157, -117.1611, 20, "United States", ()),
    ("Dallas", 32.7767, -96.7970, 131, "United States", ()),
    ("San Jose", 37.3382, -121.8863, 25, "United States", ()),
    ("Austin", 30.2672, -97.7431, 149, "United States", ()),
    ("Seattle", 47.6062, -122.3321, 53, "United States", ()),
    ("San Francisco", 37.7749, -122.4194, 16, "United States", ()),
    ("Golden Gate Bridge", 37.8199, -122.4783, 0, "United States", ()),
    ("Alcatraz", 37.8267, -122.4230, 10, "United States", ()),
    ("San Francisco Airport", 37.6213, -122.3790, 4, "United States",
     ("sfo",)),
    ("Denver", 39.7392, -104.9903, 1609, "United States", ()),
    ("Denver Airport", 39.8561, -104.6737, 1656, "United States", ()),
    ("Boston", 42.3601, -71.0589, 43, "United States", ()),
    ("Washington, D.C.", 38.9072, -77.0369, 22, "United States",
     ("washington dc", "washington d.c.")),
    ("Las Vegas", 36.1699, -115.1398, 610, "United States", ()),
    ("Hoover Dam", 36.0160, -114.7377, 375, "United States", ()),
    ("Miami", 25.7617, -80.1918, 2, "United States", ()),
    ("Atlanta", 33.7490, -84.3880, 320, "United States", ()),
    ("Atlanta Airport", 33.6407, -84.4277, 313, "United States",
     ("hartsfield",)),
    ("Portland", 45.5152, -122.6784, 15, "United States", ()),
    ("Salt Lake City", 40.7608, -111.8910, 1288, "United States", ()),
    ("Minneapolis", 44.9778, -93.2650, 264, "United States", ()),
    ("Detroit", 42.3314, -83.0458, 183, "United States", ()),
    ("Nashville", 36.1627, -86.7816, 169, "United States", ()),
    ("New Orleans", 29.9511, -90.0715, 1, "United States", ()),
    ("Honolulu", 21.3069, -157.8583, 6, "United States", ()),
    ("Anchorage", 61.2181, -149.9003, 31, "United States", ()),
    ("Orlando", 28.5383, -81.3792, 25, "United States", ()),
    ("Cape Canaveral", 28.3922, -80.6077, 3, "United States", ()),
    ("Albuquerque", 35.0844, -106.6504, 1619, "United States", ()),
    ("Pittsburgh", 40.4406, -79.9959, 373, "United States", ()),
    ("St. Louis", 38.6270, -90.1994, 142, "United States",
     ("st louis", "saint louis")),
    ("Kansas City", 39.0997, -94.5786, 277, "United States", ()),
    ("Charlotte", 35.2271, -80.8431, 229, "United States", ()),
    ("Sacramento", 38.5816, -121.4944, 9, "United States", ()),
    ("Tucson", 32.2226, -110.9747, 728, "United States", ()),
    ("Reno", 39.5296, -119.8138, 1373, "United States", ()),
    ("Boise", 43.6150, -116.2023, 824, "United States", ()),
    ("Aspen", 39.1911, -106.8175, 2438, "United States", ()),
    ("Lake Tahoe", 39.0968, -120.0324, 1897, "United States", ("tahoe",)),
    ("Sedona", 34.8697, -111.7610, 1326, "United States", ()),
    ("Moab", 38.5733, -109.5498, 1227, "United States", ()),
    ("Zion National Park", 37.2982, -113.0263, 1300, "United States",
     ("zion",)),
    ("Monument Valley", 36.9980, -110.0985, 1700, "United States", ()),
    ("Death Valley", 36.4615, -116.8655, -58, "United States", ()),
    ("Yellowstone", 44.4280, -110.5885, 2400, "United States", ()),
    ("Glacier National Park", 48.6967, -113.7180, 2026, "United States", ()),
    ("Niagara Falls", 43.0962, -79.0377, 100, "United States", ()),
    ("Mount Rushmore", 43.8791, -103.4591, 1745, "United States", ()),
    ("Crater Lake", 42.9446, -122.1090, 1883, "United States", ()),
    ("Mount Rainier", 46.8523, -121.7603, 4392, "United States",
     ("rainier",)),
    ("Mount St. Helens", 46.1912, -122.1944, 2549, "United States",
     ("mount st helens", "mt st helens", "mt. st. helens")),
    ("Mount Hood", 45.3736, -121.6960, 3429, "United States", ("mt hood",)),
    ("Mount Shasta", 41.4092, -122.1949, 4322, "United States",
     ("mt shasta",)),
    ("Mount Whitney", 36.5785, -118.2923, 4421, "United States",
     ("mt whitney",)),
    ("Pikes Peak", 38.8409, -105.0423, 4302, "United States", ()),
    ("Denali", 63.0692, -151.0070, 6190, "United States",
     ("mount mckinley",)),
    ("Mauna Kea", 19.8207, -155.4681, 4207, "United States", ()),
    ("Kilauea", 19.4069, -155.2834, 1200, "United States", ()),
    # Canada, Mexico, Central and South America
    ("Toronto", 43.6532, -79.3832, 76, "Canada", ()),
    ("Vancouver", 49.2827, -123.1207, 70, "Canada", ()),
    ("Montreal", 45.5017, -73.5673, 50, "Canada", ("montréal",)),
    ("Calgary", 51.0447, -114.0719, 1045, "Canada", ()),
    ("Banff", 51.1784, -115.5708, 1383, "Canada", ()),
    ("Mexico City", 19.4326, -99.1332, 2240, "Mexico", ()),
    ("Cancun", 21.1619, -86.8515, 10, "Mexico", ("cancún",)),
    ("Havana", 23.1136, -82.3666, 59, "Cuba", ()),
    ("Panama Canal", 9.0800, -79.6800, 26, "Panama", ()),
    ("Rio de Janeiro", -22.9068, -43.1729, 5, "Brazil", ()),
    ("São Paulo", -23.5505, -46.6333, 760, "Brazil", ("sao paulo",)),
    ("Iguazu Falls", -25.6953, -54.4367, 200, "Argentina / Brazil",
     ("iguazu",)),
    ("Buenos Aires", -34.6037, -58.3816, 25, "Argentina", ()),
    ("Aconcagua", -32.6532, -70.0109, 6961, "Argentina", ()),
    ("Santiago", -33.4489, -70.6693, 570, "Chile", ()),
    ("Lima", -12.0464, -77.0428, 154, "Peru", ()),
    ("Cusco", -13.5320, -71.9675, 3399, "Peru", ("cuzco",)),
    ("Machu Picchu", -13.1631, -72.5450, 2430, "Peru", ()),
    ("La Paz", -16.4897, -68.1193, 3640, "Bolivia", ()),
    ("Quito", -0.1807, -78.4678, 2850, "Ecuador", ()),
    ("Bogotá", 4.7110, -74.0721, 2640, "Colombia", ("bogota",)),
    # Europe
    ("London", 51.5074, -0.1278, 11, "United Kingdom", ()),
    ("Heathrow Airport", 51.4700, -0.4543, 25, "United Kingdom",
     ("heathrow",)),
    ("Stonehenge", 51.1789, -1.8262, 100, "United Kingdom", ()),
    ("Manchester", 53.4808, -2.2426, 38, "United Kingdom", ()),
    ("Edinburgh", 55.9533, -3.1883, 47, "United Kingdom", ()),
    ("Glasgow", 55.8642, -4.2518, 40, "United Kingdom", ()),
    ("Ben Nevis", 56.7969, -5.0036, 1345, "United Kingdom", ()),
    ("Dublin", 53.3498, -6.2603, 20, "Ireland", ()),
    ("Paris", 48.8566, 2.3522, 35, "France", ()),
    ("Eiffel Tower", 48.8584, 2.2945, 35, "France", ()),
    ("Charles de Gaulle Airport", 49.0097, 2.5479, 119, "France",
     ("charles de gaulle",)),
    ("Chamonix", 45.9237, 6.8694, 1035, "France", ()),
    ("Mont Blanc", 45.8326, 6.8652, 4808, "France / Italy", ()),
    ("Courchevel", 45.3967, 6.6347, 2008, "France", ()),
    ("Monaco", 43.7384, 7.4246, 50, "Monaco", ("monte carlo",)),
    ("Berlin", 52.5200, 13.4050, 34, "Germany", ()),
    ("Munich", 48.1351, 11.5820, 519, "Germany", ("münchen",)),
    ("Frankfurt", 50.1109, 8.6821, 112, "Germany", ()),
    ("Hamburg", 53.5511, 9.9937, 6, "Germany", ()),
    ("Amsterdam", 52.3676, 4.9041, 0, "Netherlands", ()),
    ("Brussels", 50.8503, 4.3517, 13, "Belgium", ()),
    ("Zurich", 47.3769, 8.5417, 408, "Switzerland", ("zürich",)),
    ("Geneva", 46.2044, 6.1432, 375, "Switzerland", ()),
    ("Interlaken", 46.6863, 7.8632, 568, "Switzerland", ()),
    ("Jungfrau", 46.5368, 7.9626, 4158, "Switzerland", ()),
    ("Innsbruck", 47.2692, 11.4041, 574, "Austria", ()),
    ("Vienna", 48.2082, 16.3738, 190, "Austria", ("wien",)),
    ("Prague", 50.0755, 14.4378, 235, "Czechia", ()),
    ("Budapest", 47.4979, 19.0402, 96, "Hungary", ()),
    ("Warsaw", 52.2297, 21.0122, 100, "Poland", ()),
    ("Madrid", 40.4168, -3.7038, 667, "Spain", ()),
    ("Barcelona", 41.3874, 2.1686, 12, "Spain", ()),
    ("Lisbon", 38.7223, -9.1393, 50, "Portugal", ()),
    ("Porto", 41.1579, -8.6291, 104, "Portugal", ()),
    ("Rome", 41.9028, 12.4964, 21, "Italy", ()),
    ("Milan", 45.4642, 9.1900, 120, "Italy", ()),
    ("Venice", 45.4408, 12.3155, 1, "Italy", ()),
    ("Florence", 43.7696, 11.2558, 50, "Italy", ()),
    ("Naples", 40.8518, 14.2681, 17, "Italy", ()),
    ("Mount Vesuvius", 40.8224, 14.4289, 1281, "Italy", ("vesuvius",)),
    ("Mount Etna", 37.7510, 14.9934, 3357, "Italy", ("etna",)),
    ("Athens", 37.9838, 23.7275, 70, "Greece", ()),
    ("Santorini", 36.3932, 25.4615, 100, "Greece", ()),
    ("Istanbul", 41.0082, 28.9784, 39, "Turkey", ()),
    ("Oslo", 59.9139, 10.7522, 23, "Norway", ()),
    ("Geiranger", 62.1008, 7.2059, 10, "Norway", ("geirangerfjord",)),
    ("Stockholm", 59.3293, 18.0686, 28, "Sweden", ()),
    ("Copenhagen", 55.6761, 12.5683, 14, "Denmark", ()),
    ("Helsinki", 60.1699, 24.9384, 17, "Finland", ()),
    ("Reykjavik", 64.1466, -21.9426, 30, "Iceland", ("reykjavík",)),
    ("Moscow", 55.7558, 37.6173, 156, "Russia", ()),
    ("Saint Petersburg", 59.9311, 30.3609, 3, "Russia",
     ("st petersburg", "st. petersburg")),
    ("Kyiv", 50.4501, 30.5234, 179, "Ukraine", ("kiev",)),
    # Asia
    ("Tokyo", 35.6762, 139.6503, 40, "Japan", ()),
    ("Haneda Airport", 35.5494, 139.7798, 6, "Japan", ("haneda",)),
    ("Osaka", 34.6937, 135.5023, 12, "Japan", ()),
    ("Kyoto", 35.0116, 135.7681, 50, "Japan", ()),
    ("Seoul", 37.5665, 126.9780, 38, "South Korea", ()),
    ("Beijing", 39.9042, 116.4074, 44, "China", ()),
    ("Great Wall of China", 40.3588, 116.0201, 800, "China",
     ("great wall",)),
    ("Shanghai", 31.2304, 121.4737, 4, "China", ()),
    ("Hong Kong", 22.3193, 114.1694, 10, "China", ()),
    ("Guilin", 25.2736, 110.2900, 150, "China", ()),
    ("Zhangjiajie", 29.1170, 110.4790, 1000, "China", ()),
    ("Lhasa", 29.6520, 91.1720, 3656, "China", ()),
    ("Taipei", 25.0330, 121.5654, 9, "Taiwan", ()),
    ("Ulaanbaatar", 47.8864, 106.9057, 1350, "Mongolia", ()),
    ("Singapore", 1.3521, 103.8198, 15, "Singapore", ()),
    ("Changi Airport", 1.3644, 103.9915, 7, "Singapore", ("changi",)),
    ("Bangkok", 13.7563, 100.5018, 2, "Thailand", ()),
    ("Kuala Lumpur", 3.1390, 101.6869, 56, "Malaysia", ()),
    ("Jakarta", -6.2088, 106.8456, 8, "Indonesia", ()),
    ("Bali", -8.4095, 115.1889, 100, "Indonesia", ()),
    ("Manila", 14.5995, 120.9842, 5, "Philippines", ()),
    ("Hanoi", 21.0278, 105.8342, 15, "Vietnam", ()),
    ("Ha Long Bay", 20.9101, 107.1839, 0, "Vietnam", ("halong bay",)),
    ("Ho Chi Minh City", 10.8231, 106.6297, 19, "Vietnam", ("saigon",)),
    ("Delhi", 28.7041, 77.1025, 216, "India", ("new delhi",)),
    ("Taj Mahal", 27.1751, 78.0421, 170, "India", ()),
    ("Mumbai", 19.0760, 72.8777, 14, "India", ("bombay",)),
    ("Bangalore", 12.9716, 77.5946, 920, "India", ("bengaluru",)),
    ("Hyderabad", 17.3850, 78.4867, 542, "India", ()),
    ("Chennai", 13.0827, 80.2707, 7, "India", ("madras",)),
    ("Kolkata", 22.5726, 88.3639, 9, "India", ("calcutta",)),
    ("Kathmandu", 27.7172, 85.3240, 1400, "Nepal", ()),
    ("Lukla", 27.6869, 86.7314, 2860, "Nepal", ()),
    ("K2", 35.8825, 76.5133, 8611, "Pakistan / China", ()),
    ("Islamabad", 33.6844, 73.0479, 540, "Pakistan", ()),
    ("Karachi", 24.8607, 67.0011, 8, "Pakistan", ()),
    ("Dubai", 25.2048, 55.2708, 5, "United Arab Emirates", ()),
    ("Burj Khalifa", 25.1972, 55.2744, 5, "United Arab Emirates", ()),
    ("Abu Dhabi", 24.4539, 54.3773, 5, "United Arab Emirates", ()),
    ("Doha", 25.2854, 51.5310, 10, "Qatar", ()),
    ("Riyadh", 24.7136, 46.6753, 612, "Saudi Arabia", ()),
    ("Tel Aviv", 32.0853, 34.7818, 5, "Israel", ()),
    ("Jerusalem", 31.7683, 35.2137, 754, "Israel", ()),
    ("Tehran", 35.6892, 51.3890, 1190, "Iran", ()),
    # Africa
    ("Cairo", 30.0444, 31.2357, 23, "Egypt", ()),
    ("Pyramids of Giza", 29.9792, 31.1342, 60, "Egypt",
     ("giza", "the pyramids")),
    ("Marrakech", 31.6295, -7.9811, 466, "Morocco", ("marrakesh",)),
    ("Casablanca", 33.5731, -7.5898, 50, "Morocco", ()),
    ("Lagos", 6.5244, 3.3792, 41, "Nigeria", ()),
    ("Addis Ababa", 9.0300, 38.7400, 2355, "Ethiopia", ()),
    ("Nairobi", -1.2921, 36.8219, 1795, "Kenya", ()),
    ("Mount Kilimanjaro", -3.0674, 37.3556, 5895, "Tanzania",
     ("kilimanjaro",)),
    ("Victoria Falls", -17.9243, 25.8572, 900, "Zambia / Zimbabwe", ()),
    ("Johannesburg", -26.2041, 28.0473, 1753, "South Africa", ()),
    ("Cape Town", -33.9249, 18.4241, 15, "South Africa", ()),
    ("Table Mountain", -33.9628, 18.4098, 1085, "South Africa", ()),
    # Oceania
    ("Sydney", -33.8688, 151.2093, 58, "Australia", ()),
    ("Sydney Opera House", -33.8568, 151.2153, 5, "Australia", ()),
    ("Melbourne", -37.8136, 144.9631, 31, "Australia", ()),
    ("Brisbane", -27.4698, 153.0251, 27, "Australia", ()),
    ("Perth", -31.9505, 115.8605, 20, "Australia", ()),
    ("Uluru", -25.3444, 131.0369, 863, "Australia", ("ayers rock",)),
    ("Auckland", -36.8485, 174.7633, 20, "New Zealand", ()),
    ("Wellington", -41.2865, 174.7762, 20, "New Zealand", ()),
    ("Queenstown", -45.0312, 168.6626, 310, "New Zealand", ()),
    ("Milford Sound", -44.6414, 167.8974, 0, "New Zealand", ()),
    ("Aoraki / Mount Cook", -43.5950, 170.1418, 3724, "New Zealand",
     ("mount cook", "aoraki")),
)


def _names(entry) -> List[str]:
    name, _lat, _lon, _elev, _country, aliases = entry
    return [name.lower(), *[a.lower() for a in aliases]]


#: Every list name, longest first, so "new york city" beats "new york" and
#: "sydney opera house" beats "sydney".
_LIST_NAMES: List[Tuple[str, Tuple]] = sorted(
    ((alias, entry) for entry in GAZETTEER for alias in _names(entry)),
    key=lambda pair: -len(pair[0]))

#: Words that put a place after them: "over Paris", "near Denver".
LOCATIVE = (r"over|above|near|around|across|in|at|from|to|towards?|outside|"
            r"off|along|past|by|into|out of|beside|between|circling|orbiting|"
            r"approaching|leaving|departing|overflying|landing at|landing in")
#: Optional words between the locative and the name.
_LEAD_IN = r"(?:(?:the|downtown|central|city of|greater|beautiful|sunny)\s+)*"


def _list_pattern(name: str) -> re.Pattern:
    escaped = re.escape(name).replace(r"\ ", r"\s+")
    return re.compile(
        rf"\b(?:{LOCATIVE})\s+{_LEAD_IN}({escaped})(?![\w'])"
        # "Paris, Texas" is not Paris: a qualifier after a comma sends
        # the phrase to OpenStreetMap instead.
        rf"(?!\s*,\s*[a-z])",
        re.IGNORECASE)


_LIST_PATTERNS: List[Tuple[re.Pattern, Tuple]] = [
    (_list_pattern(name), entry) for name, entry in _LIST_NAMES]


def lookup_list(prompt: str, skip: Iterable[str] = ()) -> Optional[Place]:
    """The built-in list's answer for the prompt (the first place it
    names), or None.

    ``skip`` holds phrases the caller already resolves (the curated bakes),
    so a list entry is never matched INSIDE one of them.
    """
    text = " ".join((prompt or "").split())
    skipped = [s.lower() for s in skip]
    best: Optional[Tuple[int, int, Tuple, str]] = None
    for pattern, entry in _LIST_PATTERNS:
        for match in pattern.finditer(text):
            phrase = match.group(1)
            if phrase.lower() in skipped:
                continue
            # The FIRST place named is where the flight is ("from Boston
            # to Chicago" starts at Boston); at one position the longest
            # name wins ("new york city" over "new york").
            key = (match.start(1), -len(phrase))
            if best is None or key < (best[0], best[1]):
                best = (key[0], key[1], entry, phrase)
            break
    if best is None:
        return None
    _, _, entry, phrase = best
    name, lat, lon, elev, country, _aliases = entry
    return Place(name=name, latitude=lat, longitude=lon,
                 elevation_m=float(elev), phrase=phrase, source=SOURCE_LIST,
                 display=f"{name}, {country}")


# -- free-text candidates for OpenStreetMap ---------------------------------

#: Words that end a place phrase ("over boston AT 500 m").
_STOP_WORDS = frozenset("""
a an and at with without in on during heading headed flying fly flies
while for under below beneath through into toward towards to from then
when where which that who as by of near over above around across after
before until via using is are was be being so but or nor if it its this
these those there here at
""".split())
#: Words that are never the start of a place name in this vocabulary.
_NOT_A_PLACE_START = frozenset("""
a an some any my our your his her their its this that these those one two
three four five six seven eight nine ten few many several each every no
light heavy moderate severe strong gusty calm clear low high dense thick
thin rough smooth bumpy windy stormy rainy snowy foggy hazy cloudy sunny
dark bright night day morning evening afternoon dusk dawn noon midnight
sunset sunrise twilight it them him her me us you formation choppy gale
golden varied various different mixed random all both every
""".split())
#: Words that make a phrase scenery or weather, not a named place.
_GENERIC = frozenset("""
the ocean oceans sea seas water waters lake lakes river rivers coast
coastline shore beach beaches bay island islands desert deserts dunes
mountain mountains mountainous ridge ridges peak peaks hill hills hillside
valley valleys canyon canyons cliff cliffs plain plains prairie prairies
grassland grasslands field fields farmland farms forest forests woods
jungle tundra glacier glaciers snow ice ground terrain land city cities
town towns village suburbs downtown countryside airport airports runway
runways airfield sky skies cloud clouds clouds weather storm storms
thunderstorm thunderstorms tornado tornadoes downburst rain fog mist haze
turbulence wind winds gust gusts shear icing lightning sun moon stars
night day altitude speed knots kt kts feet ft metres meters m km miles mph
degrees heading formation traffic wingman chase cockpit tower camera
cameras view views frames images photos video clip plane planes aircraft
airplane airplanes jet jets helicopter glider cessna boeing airbus fighter
the a an area region zone world earth surface flat open urban rural
left right north south east west northeast northwest southeast southwest
up down side behind ahead alongside overhead nearby level straight full
cruise climb descent landing takeoff approach pattern circuit loop roll
turn turns maneuver maneuvers manoeuvre manoeuvres doublet horizon sight
distance max min minimum maximum sea-level show film record capture
air force hour hours time times season seasons table file scenario row
block conditions lighting precipitation
""".split())
#: Locatives that almost always introduce a place ("over", "near"); their
#: phrases are tried first.
_STRONG_LOCATIVE = frozenset("""
over above near around across circling orbiting overflying approaching
""".split())


def candidate_phrases(prompt: str, limit: int = 2) -> List[str]:
    """Phrases after a locative word that could be a place name, those
    after a strong locative ("over", "near") first. ``limit`` bounds the
    OpenStreetMap queries one compile can make."""
    text = " ".join((prompt or "").split())
    strong: List[str] = []
    weak: List[str] = []
    for match in re.finditer(rf"\b(?:{LOCATIVE})\s+", text, re.IGNORECASE):
        rest = text[match.end():]
        words = re.findall(r"[^\s,.;:!?()]+|[,.;:!?()]", rest)
        phrase: List[str] = []
        qualifier = False
        for index, word in enumerate(words):
            low = word.lower()
            if word == "," and phrase and not qualifier:
                qualifier = True        # "Paris, Texas": keep one qualifier
                phrase.append(",")
                continue
            if not re.match(r"^[^\W\d_][\w'.&-]*$", word):
                break
            if not phrase and low in ("the",):
                continue
            if low in _STOP_WORDS and not (phrase and low in ("of", "de", "del",
                                                            "la", "le", "los",
                                                            "san", "st",
                                                            "saint")):
                break
            phrase.append(word)
            if len([w for w in phrase if w != ","]) >= 5:
                break
        while phrase and (phrase[-1] == "," or phrase[-1].lower() in
                          ("of", "de", "del", "la", "le", "los")):
            phrase.pop()
        if not phrase:
            continue
        words_only = [w for w in phrase if w != ","]
        if words_only[0].lower() in _NOT_A_PLACE_START:
            continue
        if all(w.lower().strip(".'") in _GENERIC for w in words_only):
            continue
        if re.search(r"\d", " ".join(words_only)):
            continue
        candidate = " ".join(phrase).replace(" ,", ",")
        bucket = (strong if match.group(0).strip().lower() in _STRONG_LOCATIVE
                  else weak)
        if candidate.lower() not in [c.lower() for c in strong + weak]:
            bucket.append(candidate)
    return (strong + weak)[:limit]


# -- OpenStreetMap ---------------------------------------------------------------

_LOCK = threading.Lock()
_LAST_REQUEST = [0.0]


def _cache_path() -> Path:
    return Path(os.environ.get(CACHE_ENV) or DEFAULT_CACHE)


def _read_cache() -> Dict[str, Optional[Dict]]:
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_cache(cache: Dict[str, Optional[Dict]]) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, indent=1, sort_keys=True),
                        encoding="utf-8")
    except OSError:
        pass        # a read-only checkout still geocodes, just uncached


def _fetch(query: str) -> List[Dict]:
    """One Nominatim search, spaced per the usage policy."""
    params = urllib.parse.urlencode({"q": query, "format": "jsonv2",
                                     "limit": 5, "addressdetails": 0})
    request = urllib.request.Request(f"{NOMINATIM_URL}?{params}",
                                     headers={"User-Agent": USER_AGENT,
                                              "Accept-Language": "en"})
    with _LOCK:
        wait = MIN_REQUEST_INTERVAL_S - (time.monotonic() - _LAST_REQUEST[0])
        if wait > 0:
            time.sleep(wait)
        try:
            with urllib.request.urlopen(request,
                                        timeout=REQUEST_TIMEOUT_S) as response:
                return json.loads(response.read().decode("utf-8"))
        finally:
            _LAST_REQUEST[0] = time.monotonic()


def _best_hit(hits: Sequence[Dict]) -> Optional[Dict]:
    for hit in hits:
        category = str(hit.get("category") or hit.get("class") or "")
        try:
            importance = float(hit.get("importance") or 0.0)
        except (TypeError, ValueError):
            importance = 0.0
        if category in ACCEPTED_CATEGORIES and importance >= MIN_IMPORTANCE:
            return hit
    return None


def lookup_online(phrase: str, fetch=None) -> Optional[Place]:
    """OpenStreetMap's answer for one phrase (cached), or None.

    Network failures return None: the prompt still compiles, without a
    place, and the caller says so in the notes.
    """
    key = " ".join(phrase.lower().split())
    cache = _read_cache()
    if key in cache:
        hit = cache[key]
    else:
        try:
            hits = (fetch or _fetch)(phrase)
        except Exception:           # offline, blocked, rate-limited: no place
            return None
        hit = _best_hit(hits if isinstance(hits, list) else [])
        if hit is not None:
            hit = {"lat": float(hit["lat"]), "lon": float(hit["lon"]),
                   "display_name": str(hit.get("display_name") or phrase),
                   "category": str(hit.get("category") or hit.get("class")),
                   "type": str(hit.get("type") or "")}
        cache[key] = hit
        _write_cache(cache)
    if not hit:
        return None
    display = str(hit["display_name"])
    return Place(name=display.split(",")[0], latitude=round(hit["lat"], 6),
                 longitude=round(hit["lon"], 6), elevation_m=None,
                 phrase=phrase, source=SOURCE_OSM, display=display)


# -- the entry point -------------------------------------------------------------

def mode() -> str:
    value = os.environ.get(GEOCODER_ENV, "auto").strip().lower()
    return value if value in ("auto", "offline", "off") else "auto"


def find_place(prompt: str, skip: Iterable[str] = (),
               fetch=None) -> Optional[Place]:
    """The place a prompt names, or None. See the module docstring for
    the order and the modes. ``fetch`` replaces the HTTP call (tests)."""
    current = mode()
    if current == "off" or not (prompt or "").strip():
        return None
    skip = list(skip)
    place = lookup_list(prompt, skip=skip)
    if place is not None or current == "offline":
        return place
    for phrase in candidate_phrases(prompt):
        if phrase.lower() in [s.lower() for s in skip]:
            continue
        place = lookup_online(phrase, fetch=fetch)
        if place is not None:
            return place
    return None
