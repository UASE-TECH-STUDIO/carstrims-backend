"""
AI-powered natural language search, scoped specifically to CARSTRIMS —
not a general-purpose assistant. Sends the person's free-text search
to Gemini with a prompt that describes exactly this app's domain (car
marketplace filters, Nigerian states, dealer/people search) and asks
for a structured JSON response identifying what they're looking for.

Falls back gracefully: if no API key is configured, or the Gemini call
fails/times out for any reason, the caller should fall back to the
existing regex-based parser (app/modules/cars/public_router.py) rather
than break the search entirely.
"""
import httpx
from app.config.settings import settings

GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

SYSTEM_PROMPT = """You are the search-understanding engine for CARSTRIMS, a Nigerian vehicle marketplace app (cars, and other vehicles). You are NOT a general assistant — you only ever extract vehicle-shopping search intent from what the person typed or said, in any phrasing, any language mix (including Nigerian Pidgin or mixed English), however casual or indirect.

Given the person's text, return ONLY a JSON object (no other text) with this exact shape:
{
  "intent": "search_cars" | "search_dealers" | "search_people" | "unclear",
  "vehicleType": "car" | "motorcycle" | "tricycle" | "truck" | "bus" | "van" | null,
  "brand": string or null,
  "model": string or null,
  "yearFrom": integer or null,
  "yearTo": integer or null,
  "priceMinNgn": number or null,
  "priceMaxNgn": number or null,
  "condition": "brand new" | "foreign used" | "locally used" | "salvage" | null,
  "fuelType": "petrol" | "diesel" | "electric" | "hybrid" | "gas" | null,
  "transmission": "automatic" | "manual" | "cvt" | "semi-automatic" | null,
  "state": string or null,
  "status": "available" | "sold" | null,
  "personOrDealerName": string or null,
  "remainingKeywords": string or null,
  "understoodSummary": [ { "label": string } ]
}

Rules:
- "neatly used" / "clean" / "tokunbo" / "belgium" all commonly mean "foreign used" in Nigerian car-shopping language — map them to condition "foreign used" unless context says otherwise.
- Vehicle type slang: "okada" or "bike" means motorcycle. "keke" or "napep" means tricycle. "lorry" means truck. Leave vehicleType null if the person doesn't specify — this app defaults to showing cars, not because they typed "car" but because that's most listings; only set vehicleType when they actually indicate a type.
- Price expressed as "3.5-6.5million", "3.5m to 6.5m" etc. means priceMinNgn=3500000, priceMaxNgn=6500000. "under 10m" means priceMaxNgn=10000000 only. "around 5m" means roughly priceMinNgn=4000000, priceMaxNgn=6000000.
- If the person is clearly asking to find a DEALER or PERSON by name or location ("looking for a dealer named Musa in Abuja", "dealers in Lagos"), set intent to "search_dealers" (or "search_people" if clearly not business-related), fill personOrDealerName and/or state, and leave car-specific fields null.
- If nothing meaningful can be extracted, set intent to "unclear" and leave everything else null.
- understoodSummary is a short list of what you picked up, in plain words, for display as filter chips - e.g. [{"label":"Toyota"},{"label":"2019"},{"label":"Foreign Used"},{"label":"NGN 3.5M - NGN 6.5M"}].
- Never invent a value that wasn't reasonably implied by the text.
- Output ONLY the JSON object, nothing else.
"""


async def parse_search_with_ai(text: str) -> dict | None:
    """
    Returns the parsed structured filters dict on success, or None if
    the AI parse isn't available or failed for any reason — callers
    must fall back to the regex-based parser in that case.
    """
    if not settings.GEMINI_API_KEY or not text or not text.strip():
        return None

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.post(
                GEMINI_URL,
                params={"key": settings.GEMINI_API_KEY},
                json={
                    "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                    "contents": [{"parts": [{"text": text.strip()}]}],
                    "generationConfig": {
                        "temperature": 0.1,
                        "responseMimeType": "application/json",
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
            text_out = data["candidates"][0]["content"]["parts"][0]["text"]
            import json
            parsed = json.loads(text_out)
            return parsed
    except Exception:
        # Network issue, quota exceeded, malformed response, timeout,
        # etc. — search must keep working via the regex fallback
        # rather than break because the AI call had a problem.
        return None
