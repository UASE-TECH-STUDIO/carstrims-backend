"""
AI-powered navigation intent understanding — given what someone typed
or said (in ANY phrasing, dialect, Nigerian Pidgin, mixed English,
however indirect or broken) and a list of this app's actual
available pages for their role, asks Gemini which page(s) they
almost certainly mean.

Deliberately stateless about the app's own page structure: the
CALLER passes the list of candidate pages (path/label/description)
on every request, rather than this service maintaining its own copy
that could drift out of sync with the real navigationRegistry.ts on
the frontend. Gemini is instructed to ONLY EVER return paths that
were in the provided list — this is enforced again on the frontend
by validating the response, so a hallucinated path can never make it
into an actual link.

Falls back gracefully: if no API key is configured, or the Gemini
call fails/times out for any reason, the caller should fall back to
the existing local keyword/fuzzy matcher rather than break entirely.
"""
import httpx
import json
from app.config.settings import settings

GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

SYSTEM_PROMPT = """You are the navigation-understanding engine for CARSTRIMS, a Nigerian vehicle marketplace app. You are NOT a general assistant — you only ever figure out which page in THIS app's dashboard the person is trying to reach, from what they typed or said.

People here range widely in tech confidence and phrasing — expect casual English, Nigerian Pidgin, mixed languages, broken grammar, indirect descriptions ("I want to put my car for sale" instead of "add vehicle"), or someone just describing their situation ("I am new partner wetin I go do") rather than naming a feature. Understand the INTENT behind however they phrased it, not just literal keyword matches.

You will be given:
1. The person's text.
2. A JSON list of the ONLY valid pages you may choose from, each with a "path", "label", and "description".

Return ONLY a JSON object (no other text) with this exact shape:
{
  "matches": [ { "path": string, "confidence": "high" | "medium" | "low" } ],
  "understood": string
}

Rules:
- "path" values in your response MUST be copied EXACTLY from the provided list — never invent, modify, or guess a path that wasn't given to you.
- Return 1-4 matches, ordered best-first. If genuinely nothing in the list relates to what they said, return an empty matches array.
- "understood" is a short, plain-language restatement of what you think they want, for display purposes — e.g. "wanting to add a new vehicle" or "asking how the app works". If matches is empty, briefly say why nothing matched.
- Bias toward being helpful: if there's a reasonable interpretation connecting their words to an available page, include it even at "low" confidence, rather than returning nothing.
- Never invent a page or feature that wasn't in the provided list, even if it sounds plausible for a car marketplace app.
- Output ONLY the JSON object, nothing else.
"""


async def match_navigation_with_ai(text: str, entries: list[dict]) -> dict | None:
    """
    Returns {"matches": [...], "understood": str} on success, or None
    if the AI call isn't available or failed for any reason — callers
    must fall back to local keyword/fuzzy matching in that case.
    """
    if not settings.GEMINI_API_KEY or not text or not text.strip() or not entries:
        return None

    try:
        user_content = json.dumps({
            "text": text.strip(),
            "availablePages": entries,
        })
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.post(
                GEMINI_URL,
                params={"key": settings.GEMINI_API_KEY},
                json={
                    "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                    "contents": [{"parts": [{"text": user_content}]}],
                    "generationConfig": {
                        "temperature": 0.1,
                        "responseMimeType": "application/json",
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
            text_out = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text_out)

            # Defensive validation: only keep matches whose path was
            # genuinely in the provided list, in case the model
            # slips up despite instructions - never trust AI output
            # blindly for something that produces a real navigation link.
            valid_paths = {e["path"] for e in entries}
            matches = [m for m in parsed.get("matches", []) if m.get("path") in valid_paths]

            return {"matches": matches, "understood": parsed.get("understood", "")}
    except Exception:
        # Network issue, quota exceeded, malformed response, timeout,
        # etc. — navigation search must keep working via the local
        # fallback rather than break because the AI call had a problem.
        return None
