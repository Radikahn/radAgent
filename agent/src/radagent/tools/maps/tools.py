import asyncio
import json
import math
import threading
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from strands import tool

from radagent.cards import LatLon, Place, PlacesCard, SearchCenter


NOMINATIM_URL: str = "https://nominatim.openstreetmap.org/search"
# Nominatim's usage policy asks for an identifying User-Agent and at most one request per second
USER_AGENT: str = "radagent/0.1 (personal assistant)"
MIN_REQUEST_INTERVAL_S: float = 1.0
TIMEOUT_S: int = 10
ATTRIBUTION: str = "© OpenStreetMap contributors"

DEFAULT_RADIUS_KM: float = 5.0
MAX_RADIUS_KM: float = 50.0
MAX_PLACES: int = 10
# Bounded searches come back in no particular order, so fetch extra and keep the closest
NEARBY_CANDIDATES: int = 40
# Same-named results this close together are one place mapped several times (a building and its shop, or
# a bridge and its road segments); landmark searches use the wider gap since they look for one thing
DUPLICATE_GAP_NEARBY_M: int = 100
DUPLICATE_GAP_LANDMARK_M: int = 5_000

# Everyday words Nominatim doesn't know, mapped to the OpenStreetMap category it does
_QUERY_ALIASES: dict[str, str] = {"coffee": "cafe", "coffee shop": "cafe", "coffee shops": "cafe", "cafes": "cafe"}

_LOCALITY_KEYS: tuple[str, ...] = ("city", "town", "village", "hamlet", "suburb", "municipality")

_request_lock = threading.Lock()
_last_request_at: float = 0.0



# ---- Nominatim ----

def _nominatim(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Run one Nominatim search, spacing requests out to respect its rate limit"""
    global _last_request_at
    url = f"{NOMINATIM_URL}?{urlencode({**params, 'format': 'jsonv2'})}"
    request = Request(url, headers = {"User-Agent": USER_AGENT})

    with _request_lock:
        wait = _last_request_at + MIN_REQUEST_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            with urlopen(request, timeout = TIMEOUT_S) as response:
                return json.load(response)
        finally:
            _last_request_at = time.monotonic()


def _distance_m(a: LatLon, b: LatLon) -> int:
    """Great-circle distance in meters"""
    lat1, lat2 = math.radians(a["lat"]), math.radians(b["lat"])
    dlat = lat2 - lat1
    dlon = math.radians(b["lon"] - a["lon"])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return round(2 * 6_371_000 * math.asin(math.sqrt(h)))


def _viewbox(center: LatLon, radius_km: float) -> str:
    """Nominatim viewbox (lon1,lat1,lon2,lat2) for a square around `center`"""
    dlat = radius_km / 111.32
    dlon = radius_km / (111.32 * max(math.cos(math.radians(center["lat"])), 0.01))
    return f"{center['lon'] - dlon},{center['lat'] + dlat},{center['lon'] + dlon},{center['lat'] - dlat}"



# ---- Shaping results into the card contract ----

def _format_address(item: dict[str, Any]) -> str | None:
    address: dict[str, str] = item.get("address") or {}
    street = " ".join(part for part in (address.get("house_number"), address.get("road")) if part)
    locality = next((address[key] for key in _LOCALITY_KEYS if address.get(key)), None)
    region = " ".join(part for part in (address.get("state"), address.get("postcode")) if part)
    parts = [part for part in (street, locality, region) if part]
    if parts:
        return ", ".join(parts)

    # Fall back to the full display name minus the leading place name
    display: str = item.get("display_name") or ""
    name: str = item.get("name") or ""
    if name and display.startswith(name + ", "):
        display = display[len(name) + 2:]
    return display or None


def _to_place(item: dict[str, Any], center: LatLon | None) -> Place:
    tags: dict[str, str] = item.get("extratags") or {}
    location: LatLon = {"lat": float(item["lat"]), "lon": float(item["lon"])}
    # Generic tags like building=yes say nothing in their value, so the key names the category instead
    kind = item.get("type") if item.get("type") not in (None, "", "yes") else item.get("category")
    category = (kind or "place").replace("_", " ").capitalize()
    name: str = item.get("name") or tags.get("brand") or category
    address = _format_address(item)
    coordinates = f"{location['lat']},{location['lon']}"

    return {
        "id": f"osm:{item.get('osm_type')}:{item.get('osm_id')}",
        "name": name,
        "category": category,
        "address": address,
        "location": location,
        "distance_m": _distance_m(center, location) if center else None,
        "phone": tags.get("phone") or tags.get("contact:phone"),
        "website": tags.get("website") or tags.get("contact:website"),
        "opening_hours": tags.get("opening_hours"),
        "links": {
            "osm": f"https://www.openstreetmap.org/{item.get('osm_type')}/{item.get('osm_id')}",
            "google_maps": "https://www.google.com/maps/search/?api=1&query="
                + quote(f"{name}, {address}" if address else coordinates),
            "apple_maps": f"https://maps.apple.com/?q={quote(name)}&ll={coordinates}",
        },
    }


def _dedupe(places: list[Place], gap_m: int) -> list[Place]:
    """Drop places that share a name with an earlier, more relevant place within `gap_m` meters"""
    kept: list[Place] = []
    for place in places:
        if not any(
            other["name"].casefold() == place["name"].casefold()
            and _distance_m(other["location"], place["location"]) <= gap_m
            for other in kept
        ):
            kept.append(place)
    return kept


def _search(query: str, near: str | None, radius_km: float, limit: int) -> PlacesCard | str:
    """
    Search for places, returning a card or the reason nothing could be shown

    Args:
        query: {str} Category word, name or address
        near: {str | None} Where to search around
        radius_km: {float} Search radius around `near`
        limit: {int} Maximum places to return

    Returns:
        result: {PlacesCard | str}
    """
    center: SearchCenter | None = None
    if near:
        matches = _nominatim({"q": near, "limit": 1})
        if not matches:
            return f"Could not find the location {near!r}. Try a fuller name, e.g. with the city and state."
        center = {"label": near, "location": {"lat": float(matches[0]["lat"]), "lon": float(matches[0]["lon"])}}

    query = _QUERY_ALIASES.get(query.casefold(), query)
    params: dict[str, Any] = {"q": query, "addressdetails": 1, "extratags": 1, "limit": NEARBY_CANDIDATES}
    if center:
        params |= {"viewbox": _viewbox(center["location"], radius_km), "bounded": 1}

    places = [_to_place(item, center["location"] if center else None) for item in _nominatim(params)]
    if center:
        places.sort(key = lambda place: place["distance_m"] or 0)
    places = _dedupe(places, DUPLICATE_GAP_NEARBY_M if center else DUPLICATE_GAP_LANDMARK_M)[:limit]

    if not places:
        where = f" within {radius_km:g} km of {near}" if near else ""
        return (
            f"No places matched {query!r}{where}. OpenStreetMap matches names and categories, so retry with a "
            f"category word (e.g. 'cafe' instead of 'coffee') or a larger radius."
        )

    return {
        "card": "places",
        "version": 1,
        "query": query,
        "near": center,
        "places": places,
        "attribution": ATTRIBUTION,
    }



def _summary(card: PlacesCard) -> str:
    """What the model sees: enough to comment on the places, small enough that the harness never offloads it"""
    lines = [
        f"Found {len(card['places'])} places. The user already sees them as map cards with address, distance, "
        f"hours, phone and map links, so don't list those again: reply in a sentence or two, e.g. which you'd pick.",
    ]
    for number, place in enumerate(card["places"], start = 1):
        details = [place["category"]]
        if place["distance_m"] is not None:
            details.append(f"{place['distance_m'] / 1000:.1f} km")
        if place["opening_hours"]:
            details.append(place["opening_hours"])
        lines.append(f"{number}. {place['name']} ({'; '.join(details)}) {place['address'] or ''}".rstrip())
    return "\n".join(lines)



@tool
async def find_places(
    query: str,
    near: str | None = None,
    radius_km: float = DEFAULT_RADIUS_KM,
    limit: int = 5,
) -> AsyncIterator[dict[str, Any]]:
    """Find places on a map: businesses, restaurants, shops, landmarks, parks, addresses and so on. Use this for any request to find, locate or look up a place, or for things near somewhere. The user sees the results as map cards with name, address, distance, hours and map links, so keep your reply short and don't repeat those details unless asked.

    Search runs on OpenStreetMap, which matches names and categories rather than descriptions. Pass a category word ("cafe", "restaurant", "sushi", "supermarket", "pharmacy", "park", "gas station") or a business or landmark name, not a phrase like "good spots for coffee". If nothing is found, retry with another category word or a larger radius.

    Args:
        query: What to look for: a category word, a business or landmark name, or an address.
        near: Where to search around, e.g. "Silver Creek, San Jose, CA". Omit when the query is itself a specific landmark or address.
        radius_km: How far from `near` to search, in kilometers.
        limit: Maximum number of places to return, 1 to 10.
    """
    limit = min(max(limit, 1), MAX_PLACES)
    radius_km = min(max(radius_km, 0.5), MAX_RADIUS_KM)

    try:
        result = await asyncio.to_thread(_search, query.strip(), (near or "").strip() or None, radius_km, limit)
    except Exception as e:
        yield {"status": "error", "content": [{"text": f"find_places failed: {type(e).__name__}: {e}"}]}
        return

    if isinstance(result, str):
        yield {"status": "success", "content": [{"text": result}]}
        return

    # The card goes to the client as a stream event; the last yield is the result the model sees
    yield result
    yield {"status": "success", "content": [{"text": _summary(result)}]}
