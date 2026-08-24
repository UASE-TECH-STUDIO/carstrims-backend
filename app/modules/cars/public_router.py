from fastapi import APIRouter, Depends, Query, Body
from typing import Optional
from app.auth.dependencies import get_current_user, get_current_dealer, get_current_dealer_or_staff
from app.modules.dealers.service import get_dealer_by_user_id, serialize_doc
from app.utils.qr_service import generate_dealer_qr, get_dealer_qr
from app.utils.comments_service import add_comment, get_car_comments, delete_comment, add_reply, toggle_comment_like, get_comment_like_status
from app.utils.ai_search_service import parse_search_with_ai
from app.utils.nav_search_service import match_navigation_with_ai
from app.modules.users.user_service import toggle_like, get_user_likes, add_favorite, remove_favorite
from app.modules.cars.service import get_public_cars, get_car_by_id
from app.database.connection import get_db
from bson import ObjectId
from pydantic import BaseModel
from app.config.settings import settings
from datetime import datetime
import time
import math
import hashlib
import re


class CommentBody(BaseModel):
    text: str


class ReplyBody(BaseModel):
    text: str


router = APIRouter(prefix="/api/v1/public", tags=["Public Feed"])

# Simple short-lived cache: the set of approved dealer IDs barely changes
# (only when a dealer gets approved/suspended), yet it was being
# re-fetched — up to 10,000 documents — on EVERY single feed request.
# A short TTL cache turns that into one fetch per ~60 seconds shared
# across all users, instead of one fetch per request.
_approved_dealers_cache: dict = {"ids": None, "at": 0.0}
_APPROVED_DEALERS_TTL_SECONDS = 60


async def get_approved_dealer_ids(db) -> list:
    now = time.time()
    if _approved_dealers_cache["ids"] is not None and (now - _approved_dealers_cache["at"]) < _APPROVED_DEALERS_TTL_SECONDS:
        return _approved_dealers_cache["ids"]

    approved_dealers = await db["dealer_organizations"].find(
        {"status": "approved"}, {"_id": 1, "dealerId": 1}
    ).to_list(10000)
    approved_ids: list = []
    for d in approved_dealers:
        str_id = str(d["_id"])
        approved_ids.append(str_id)
        try:
            approved_ids.append(ObjectId(str_id))
        except Exception:
            pass
        if d.get("dealerId"):
            approved_ids.append(d["dealerId"])

    _approved_dealers_cache["ids"] = approved_ids
    _approved_dealers_cache["at"] = now
    return approved_ids


#  PUBLIC CAR FEED 

@router.get("/cars")
async def public_car_feed(
    search: Optional[str] = Query(None),
    brand: Optional[str] = Query(None),
    condition: Optional[str] = Query(None),
    transmission: Optional[str] = Query(None),
    fuel_type: Optional[str] = Query(None),
    status: Optional[str] = Query("available"),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    city: Optional[str] = Query(None),
    year_from: Optional[int] = Query(None),
    year_to: Optional[int] = Query(None),
    color: Optional[str] = Query(None),
    max_mileage: Optional[float] = Query(None),
    vehicle_type: Optional[str] = Query(None),
    promo_only: Optional[bool] = Query(None),
    sort: Optional[str] = Query("newest"),
    skip: int = Query(0),
    limit: int = Query(20),
    seed: Optional[str] = Query(None, description="A per-session random seed from the frontend, so ordering stays stable while scrolling/paginating but changes on each fresh visit."),
):
    db = get_db()
    query: dict = {}

    if status and status != "all":
        query["status"] = status

    understood_filters: list = []  # itemized, human-readable summary of what the search text was understood as — returned to the frontend to show as adjustable filter chips, like Jiji
    leftover_keywords: list = []  # descriptive words that are a soft ranking preference, not a hard filter requirement
    ai_handled = False

    if search:
        # Try real AI understanding first (Gemini, scoped to this
        # app's own domain via the prompt in ai_search_service.py).
        # Falls back to the regex-based parser below if no API key is
        # configured, or the call fails/times out for any reason —
        # search must never break because of an AI hiccup.
        ai_result = await parse_search_with_ai(search)
        if ai_result and isinstance(ai_result, dict) and ai_result.get("intent") == "search_cars":
            ai_filters: list = []

            def _clean_str(v):
                return v.strip() if isinstance(v, str) and v.strip() else None

            vtype_val = _clean_str(ai_result.get("vehicleType"))
            if vtype_val in ("car", "motorcycle", "tricycle", "truck", "bus", "van"):
                if vtype_val == "car":
                    ai_filters.append({"$or": [{"vehicleType": "car"}, {"vehicleType": {"$exists": False}}, {"vehicleType": None}]})
                else:
                    ai_filters.append({"vehicleType": vtype_val})

            brand_val = _clean_str(ai_result.get("brand"))
            if brand_val:
                ai_filters.append({"brand": {"$regex": re.escape(brand_val), "$options": "i"}})

            model_val = _clean_str(ai_result.get("model"))
            if model_val:
                ai_filters.append({"model": {"$regex": re.escape(model_val), "$options": "i"}})

            year_from = ai_result.get("yearFrom")
            year_to = ai_result.get("yearTo")
            if isinstance(year_from, int) and 1980 <= year_from <= 2035:
                if isinstance(year_to, int) and 1980 <= year_to <= 2035 and year_to != year_from:
                    ai_filters.append({"year": {"$gte": min(year_from, year_to), "$lte": max(year_from, year_to)}})
                else:
                    ai_filters.append({"year": year_from})

            price_min = ai_result.get("priceMinNgn")
            price_max = ai_result.get("priceMaxNgn")
            price_cond: dict = {}
            if isinstance(price_min, (int, float)) and price_min > 0:
                price_cond["$gte"] = price_min
            if isinstance(price_max, (int, float)) and price_max > 0:
                price_cond["$lte"] = price_max
            if price_cond:
                query["sellingPrice"] = price_cond

            condition_val = _clean_str(ai_result.get("condition"))
            if condition_val:
                ai_filters.append({"condition": {"$regex": re.escape(condition_val), "$options": "i"}})

            fuel_val = _clean_str(ai_result.get("fuelType"))
            if fuel_val:
                ai_filters.append({"fuelType": {"$regex": re.escape(fuel_val), "$options": "i"}})

            trans_val = _clean_str(ai_result.get("transmission"))
            if trans_val:
                ai_filters.append({"transmission": {"$regex": re.escape(trans_val), "$options": "i"}})

            state_val = _clean_str(ai_result.get("state"))
            if state_val:
                ai_filters.append({"state": {"$regex": re.escape(state_val), "$options": "i"}})

            status_val = _clean_str(ai_result.get("status"))
            if status_val in ("available", "sold"):
                query["status"] = status_val

            # Same principle as the regex fallback: remaining
            # descriptive words are a soft preference used for
            # ranking, not a hard requirement that can zero out
            # results just because a car's description doesn't
            # happen to mention them.
            keywords_val = _clean_str(ai_result.get("remainingKeywords"))
            leftover_keywords = keywords_val.split() if keywords_val else []

            if ai_filters:
                query["$and"] = query.get("$and", []) + ai_filters

            summary = ai_result.get("understoodSummary")
            if isinstance(summary, list):
                for item in summary:
                    if isinstance(item, dict) and item.get("label"):
                        # AI-derived chips don't map to a literal text
                        # span in the original search string the way
                        # regex-matched ones do, so matchedText is left
                        # empty — the frontend clears the whole search
                        # box on removal for these instead of trying a
                        # precise partial-text removal.
                        understood_filters.append({"type": "ai", "label": str(item["label"])[:60], "matchedText": ""})

            ai_handled = True

    if search and not ai_handled:
        # Voice input sometimes transcribes numbers as words instead
        # of digits ("three million" rather than "3 million") — the
        # price regex below only recognizes digits, so normalize
        # common number words first, whether typed or spoken.
        NUMBER_WORDS = {
            "one":"1","two":"2","three":"3","four":"4","five":"5","six":"6",
            "seven":"7","eight":"8","nine":"9","ten":"10","eleven":"11","twelve":"12",
            "thirteen":"13","fourteen":"14","fifteen":"15","twenty":"20","thirty":"30",
            "forty":"40","fifty":"50","half":"0.5",
        }
        def _normalize_number_words(s: str) -> str:
            words = s.split()
            out = []
            i = 0
            while i < len(words):
                w = words[i]
                low = w.lower().strip(".,!?;:")
                if low in NUMBER_WORDS:
                    # "three point five" -> "3.5"
                    if i + 2 < len(words) and words[i+1].lower() == "point" and words[i+2].lower().strip(".,!?;:") in NUMBER_WORDS:
                        out.append(f"{NUMBER_WORDS[low]}.{NUMBER_WORDS[words[i+2].lower().strip('.,!?;:')]}")
                        i += 3
                        continue
                    out.append(NUMBER_WORDS[low])
                else:
                    out.append(w)
                i += 1
            return " ".join(out)

        search = _normalize_number_words(search)

        # Price-range phrases, parsed BEFORE the token-by-token pass
        # below, so "3.5-6.5million" or "under 10m" become a real
        # price filter instead of being treated as unmatched text.
        # Handles: "3.5-6.5million", "3.5m to 6.5m", "under 10m",
        # "below 5 million", "over 20m", "above 15million",
        # "around 5m" (+/-20%).
        price_search = search
        MILLION = 1_000_000

        def _num(s: str) -> float:
            return float(s.replace(",", ""))

        def _fmt_money(n: float) -> str:
            return f"NGN {n/MILLION:.1f}M" if n % MILLION else f"NGN {int(n/MILLION)}M"

        range_match = re.search(
            r"(\d+(?:\.\d+)?)\s*(?:m|million)?\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*(?:m|million)\b",
            price_search, re.IGNORECASE,
        )
        under_match = re.search(r"\b(?:under|below|less than|not more than)\s*(?:n|ngn|₦)?\s*(\d+(?:\.\d+)?)\s*(m|million)\b", price_search, re.IGNORECASE)
        over_match = re.search(r"\b(?:over|above|more than|at least)\s*(?:n|ngn|₦)?\s*(\d+(?:\.\d+)?)\s*(m|million)\b", price_search, re.IGNORECASE)
        around_match = re.search(r"\b(?:around|about|roughly|approximately)\s*(?:n|ngn|₦)?\s*(\d+(?:\.\d+)?)\s*(m|million)\b", price_search, re.IGNORECASE)

        price_filter: dict = {}
        if range_match:
            lo, hi = _num(range_match.group(1)) * MILLION, _num(range_match.group(2)) * MILLION
            price_filter = {"$gte": min(lo, hi), "$lte": max(lo, hi)}
            price_search = price_search[:range_match.start()] + price_search[range_match.end():]
            understood_filters.append({"type": "price", "label": f"{_fmt_money(min(lo,hi))} - {_fmt_money(max(lo,hi))}", "matchedText": range_match.group(0)})
        elif under_match:
            val = _num(under_match.group(1)) * MILLION
            price_filter = {"$lte": val}
            price_search = price_search[:under_match.start()] + price_search[under_match.end():]
            understood_filters.append({"type": "price", "label": f"Under {_fmt_money(val)}", "matchedText": under_match.group(0)})
        elif over_match:
            val = _num(over_match.group(1)) * MILLION
            price_filter = {"$gte": val}
            price_search = price_search[:over_match.start()] + price_search[over_match.end():]
            understood_filters.append({"type": "price", "label": f"Over {_fmt_money(val)}", "matchedText": over_match.group(0)})
        elif around_match:
            center = _num(around_match.group(1)) * MILLION
            price_filter = {"$gte": center * 0.8, "$lte": center * 1.2}
            price_search = price_search[:around_match.start()] + price_search[around_match.end():]
            understood_filters.append({"type": "price", "label": f"Around {_fmt_money(center)}", "matchedText": around_match.group(0)})

        if price_filter:
            query["sellingPrice"] = price_filter
            search = price_search.strip()

        # Strip filler/modifier words that don't change meaning but
        # would otherwise become noise in the leftover text match —
        # "neatly used", "very clean", "close to me" etc.
        search = re.sub(
            r"\b(neatly|nicely|fairly|very|really|super|extremely|clean|close to me|near me|around me|nearby)\b",
            " ", search, flags=re.IGNORECASE,
        ).strip()

    if search:
        # Smart search: recognize known vocabulary tokens (brand, year,
        # condition, fuel type, transmission) as structured filters
        # extracted right out of free text — e.g. "camry 2019 used
        # automatic" becomes year=2019 AND condition~used AND
        # transmission~automatic, with "camry" left over as a plain
        # text match against brand/model/color/carId/description. This
        # replaces needing a separate filter UI for a lot of common
        # searches. Vocabulary is deliberately scoped to this app's own
        # domain (car shopping), not general-purpose language.
        BRAND_WORDS = {b.lower(): b for b in ["Toyota","Honda","Mercedes","Mercedes-Benz","Benz","BMW","Lexus","Ford","Hyundai","Kia","Chevrolet","Audi","Land Rover","Landrover","Jeep","Volkswagen","VW","Nissan","Mazda","Peugeot","Mitsubishi","Subaru","Isuzu"]}
        CONDITION_WORDS = {"new": "new", "used": "used", "foreign": "foreign", "local": "local", "locally": "local", "salvage": "salvage"}
        FUEL_WORDS = {"petrol": "petrol", "diesel": "diesel", "electric": "electric", "hybrid": "hybrid", "gas": "gas"}
        TRANSMISSION_WORDS = {"automatic": "automatic", "manual": "manual", "cvt": "cvt", "semi-automatic": "semi-automatic"}
        STATUS_WORDS = {"available": "available", "sold": "sold"}
        STATE_WORDS = {s.lower(): s for s in ["Abuja","Lagos","Kano","Rivers","Oyo","Kaduna","Anambra","Enugu","Delta","Ogun","Imo","Ondo","Kwara","Benue","Edo","Ekiti","Cross River"]}
        COLOR_WORDS = {c.lower(): c for c in ["Black","White","Silver","Grey","Gray","Red","Blue","Green","Gold","Brown","Beige","Maroon","Orange","Yellow","Purple","Wine","Cream","Navy"]}
        VEHICLE_TYPE_WORDS = {
            "car": "car", "cars": "car",
            "motorcycle": "motorcycle", "motorbike": "motorcycle", "bike": "motorcycle", "okada": "motorcycle",
            "tricycle": "tricycle", "keke": "tricycle", "napep": "tricycle",
            "truck": "truck", "lorry": "truck",
            "bus": "bus", "minibus": "bus",
            "van": "van",
        }

        # Generic English filler that doesn't carry car-shopping
        # meaning ("that is it should be like", "I want to buy", "a
        # car" etc.) — stripped so it doesn't pollute the leftover
        # keyword match or get shown as a confusing filter chip.
        SEARCH_STOPWORDS = {
            "a","an","the","that","this","is","are","it","should","be","like","i",
            "want","need","looking","for","to","buy","get","find","some","any",
            "vehicle","vehicles","one","with","and","or","can",
            "colour","color","range","within","from","of","in","having",
        }

        tokens = search.strip().split()
        leftover_tokens = []
        smart_filters: list = []

        for tok in tokens:
            tok = tok.strip(".,!?;:()[]\"'")
            if not tok:
                continue
            low = tok.lower()
            if low.isdigit() and len(low) == 4 and 1980 <= int(low) <= 2035:
                smart_filters.append({"year": int(low)})
                understood_filters.append({"type": "year", "label": low, "matchedText": tok})
            elif low in BRAND_WORDS:
                smart_filters.append({"brand": {"$regex": re.escape(BRAND_WORDS[low]), "$options": "i"}})
                understood_filters.append({"type": "brand", "label": BRAND_WORDS[low], "matchedText": tok})
            elif low in CONDITION_WORDS:
                smart_filters.append({"condition": {"$regex": CONDITION_WORDS[low], "$options": "i"}})
                understood_filters.append({"type": "condition", "label": tok.capitalize(), "matchedText": tok})
            elif low in FUEL_WORDS:
                smart_filters.append({"fuelType": {"$regex": FUEL_WORDS[low], "$options": "i"}})
                understood_filters.append({"type": "fuel", "label": tok.capitalize(), "matchedText": tok})
            elif low in TRANSMISSION_WORDS:
                smart_filters.append({"transmission": {"$regex": TRANSMISSION_WORDS[low], "$options": "i"}})
                understood_filters.append({"type": "transmission", "label": tok.capitalize(), "matchedText": tok})
            elif low in STATUS_WORDS:
                query["status"] = STATUS_WORDS[low]  # overrides the default "available" status param
                understood_filters.append({"type": "status", "label": tok.capitalize(), "matchedText": tok})
            elif low in STATE_WORDS:
                smart_filters.append({"state": {"$regex": STATE_WORDS[low], "$options": "i"}})
                understood_filters.append({"type": "state", "label": STATE_WORDS[low], "matchedText": tok})
            elif low in COLOR_WORDS:
                smart_filters.append({"color": {"$regex": COLOR_WORDS[low], "$options": "i"}})
                understood_filters.append({"type": "color", "label": COLOR_WORDS[low], "matchedText": tok})
            elif low in VEHICLE_TYPE_WORDS:
                vt = VEHICLE_TYPE_WORDS[low]
                if vt == "car":
                    smart_filters.append({"$or": [{"vehicleType": "car"}, {"vehicleType": {"$exists": False}}, {"vehicleType": None}]})
                else:
                    smart_filters.append({"vehicleType": vt})
                understood_filters.append({"type": "vehicleType", "label": vt.capitalize(), "matchedText": tok})
            elif low in SEARCH_STOPWORDS:
                continue  # generic filler — drop entirely, not even kept as leftover
            else:
                leftover_tokens.append(tok)

        if smart_filters:
            query["$and"] = query.get("$and", []) + smart_filters

        # Leftover words (things like "neatly used" nuance, "not more
        # than a year", or anything else that isn't a recognized major
        # filter) are treated as a SOFT preference, not a requirement —
        # they're checked against the description and other fields to
        # rank matching cars higher, but a car that doesn't happen to
        # mention them is still shown. Major filters (brand, color,
        # price, year, condition, etc.) always control which cars show
        # up at all; leftover words never zero out results on their
        # own the way they used to when they were required matches.
        leftover_keywords = leftover_tokens
        if leftover_tokens:
            understood_filters.append({"type": "keyword", "label": " ".join(leftover_tokens), "matchedText": " ".join(leftover_tokens)})

    if brand:
        query["brand"] = {"$regex": brand, "$options": "i"}
    if condition:
        query["condition"] = {"$regex": condition, "$options": "i"}
    if transmission:
        query["transmission"] = {"$regex": transmission, "$options": "i"}
    if fuel_type:
        query["fuelType"] = {"$regex": fuel_type, "$options": "i"}
    if color:
        query["color"] = {"$regex": color, "$options": "i"}
    if max_mileage is not None:
        query["mileage"] = {"$lte": max_mileage}
    if promo_only:
        query["promoPrice"] = {"$exists": True, "$ne": None, "$gt": 0}
    if vehicle_type:
        # Existing listings have no vehicleType field at all (added
        # after they were created) - since they're all cars, treat a
        # missing field as "car" too, rather than hiding them from a
        # "car" filter just because they predate this field. Uses
        # $and with a nested $or (not the top-level $or) since city
        # below also needs the top-level $or for its own purposes -
        # merging both into one $or would incorrectly treat "matches
        # this city" and "is a car" as interchangeable alternatives
        # instead of both being required.
        if vehicle_type == "car":
            query["$and"] = query.get("$and", []) + [
                {"$or": [{"vehicleType": "car"}, {"vehicleType": {"$exists": False}}, {"vehicleType": None}]}
            ]
        else:
            query["vehicleType"] = vehicle_type
    if city:
        query["$or"] = query.get("$or", []) + [
            {"city": {"$regex": city, "$options": "i"}},
            {"state": {"$regex": city, "$options": "i"}},
        ]
    if min_price is not None:
        query.setdefault("sellingPrice", {})["$gte"] = min_price
    if max_price is not None:
        query.setdefault("sellingPrice", {})["$lte"] = max_price
    if year_from is not None:
        query.setdefault("year", {})["$gte"] = year_from
    if year_to is not None:
        query.setdefault("year", {})["$lte"] = year_to

    sort_field = "createdAt"
    sort_dir = -1
    if sort == "price_asc":
        sort_field, sort_dir = "sellingPrice", 1
    elif sort == "price_desc":
        sort_field, sort_dir = "sellingPrice", -1
    elif sort == "popular":
        sort_field, sort_dir = "viewCount", -1

    # Only show cars from approved dealers in the public feed
    approved_ids = await get_approved_dealer_ids(db)
    if approved_ids:
        query["dealerId"] = {"$in": approved_ids}

    total = await db["car_listings"].count_documents(query)

    if sort == "score":
        # Personalized-feeling feed: recency + engagement scoring, like
        # before, but reworked in two important ways:
        #
        # 1. The randomness is now a deterministic hash of (seed, carId)
        #    instead of MongoDB's $rand, which re-evaluates on every
        #    request — with pagination (skip/limit), that could cause
        #    the same car to appear twice, or another to get skipped
        #    entirely, as the "random" order silently shifted between
        #    page 1 and page 2 of the same scroll session. The frontend
        #    generates one seed per fresh visit/refresh (not per
        #    scroll-fetch) and sends it with every page, so ordering is
        #    now fully stable while scrolling, but genuinely different
        #    each time the app is opened or refreshed — and different
        #    seeds naturally land differently per person too.
        #
        # 2. Dealer-diversity interleaving: cars are grouped by dealer
        #    (each dealer's own cars keep their relative score order),
        #    then taken round-robin across dealers — so one dealer
        #    posting a lot doesn't dominate several consecutive feed
        #    slots, while dealers with generally higher-scoring cars
        #    still get interleaved earlier in each round.
        candidates = await db["car_listings"].find(query).sort("createdAt", -1).limit(3000).to_list(3000)

        now = datetime.utcnow()
        effective_seed = seed or "default-seed"

        for c in candidates:
            created = c.get("createdAt") or now
            try:
                age_hours = max(0.0, (now - created).total_seconds() / 3600)
            except TypeError:
                age_hours = 0.0
            recency = 10000.0 if age_hours <= 2 else 100.0 * math.exp(-0.008 * age_hours)
            engagement = (c.get("viewCount", 0) or 0) * 0.3 + (c.get("likeCount", 0) or 0) * 2.0
            h = hashlib.md5(f"{effective_seed}:{c.get('carId','')}".encode()).hexdigest()
            jitter = (int(h[:8], 16) / 0xFFFFFFFF) * 300

            # Soft boost for leftover descriptive words ("neatly used",
            # "not more than a year", etc.) — checked against the
            # car's own text fields and added as a BONUS on top of the
            # normal score, never as a requirement. A car that doesn't
            # mention "neatly used" still shows up for a "Toyota black
            # 3 million neatly used" search, just not boosted above
            # ones that do mention it.
            keyword_bonus = 0.0
            if leftover_keywords:
                haystack = " ".join([
                    str(c.get("description") or ""), str(c.get("brand") or ""),
                    str(c.get("model") or ""), str(c.get("color") or ""),
                    str(c.get("condition") or ""),
                ]).lower()
                matches = sum(1 for kw in leftover_keywords if kw.lower() in haystack)
                keyword_bonus = matches * 200.0  # meaningful boost, but never larger than the "brand new listing" recency spike

            c["_feedScore"] = recency + engagement + jitter + keyword_bonus

        candidates.sort(key=lambda c: c["_feedScore"], reverse=True)

        by_dealer: dict = {}
        dealer_order: list = []
        for c in candidates:
            did = c.get("dealerId", "unknown")
            if did not in by_dealer:
                by_dealer[did] = []
                dealer_order.append(did)
            by_dealer[did].append(c)

        interleaved: list = []
        while any(by_dealer[d] for d in dealer_order):
            for d in dealer_order:
                if by_dealer[d]:
                    interleaved.append(by_dealer[d].pop(0))

        cars = interleaved[skip:skip + limit]
    else:
        cars = await db["car_listings"].find(query).sort(sort_field, sort_dir).skip(skip).limit(limit).to_list(limit)

    # Batch-fetch dealer info for this page in ONE query instead of one
    # query per car (was 20 sequential database round-trips per page —
    # the main cause of the feed feeling slow to load).
    page_dealer_ids = list({
        car["dealerId"] for car in cars
        if ObjectId.is_valid(car.get("dealerId", ""))
    })
    dealers_by_id = {}
    if page_dealer_ids:
        dealer_docs = await db["dealer_organizations"].find(
            {"_id": {"$in": [ObjectId(d) for d in page_dealer_ids]}}
        ).to_list(len(page_dealer_ids))
        dealers_by_id = {str(d["_id"]): d for d in dealer_docs}

    result = []
    for car in cars:
        s = serialize_doc(car)
        dealer = dealers_by_id.get(car.get("dealerId"))
        if dealer:
            s["dealerName"] = dealer.get("companyName")
            s["dealerLogo"] = dealer.get("logo")
            s["dealerWhatsapp"] = dealer.get("whatsapp")
            s["dealerId"] = dealer.get("dealerId")
            s["state"] = car.get("state") or dealer.get("state")
        result.append(s)

    return {"total": total, "cars": result, "skip": skip, "limit": limit, "understoodFilters": understood_filters}


@router.get("/cars/{car_id}")
async def public_car_detail(car_id: str):
    db = get_db()
    if ObjectId.is_valid(car_id):
        car = await db["car_listings"].find_one({"_id": ObjectId(car_id), "status": {"$ne": "draft"}})
    else:
        car = await db["car_listings"].find_one({"carId": car_id, "status": {"$ne": "draft"}})

    if not car:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Car not found")

    await db["car_listings"].update_one({"_id": car["_id"]}, {"$inc": {"viewCount": 1}})

    serialized = serialize_doc(car)

    dealer = await db["dealer_organizations"].find_one(
        {"_id": ObjectId(car["dealerId"])}
    ) if ObjectId.is_valid(car.get("dealerId", "")) else None

    if dealer:
        serialized["dealer"] = {
            "dealerId": dealer.get("dealerId"),
            "companyName": dealer.get("companyName"),
            "ownerName": dealer.get("ownerName"),
            "logo": dealer.get("logo"),
            "phone": dealer.get("phone"),
            "whatsapp": dealer.get("whatsapp"),
            "email": dealer.get("email"),
            "city": dealer.get("city"),
            "state": dealer.get("state"),
            "qrCode": dealer.get("qrCode"),
            "userId": dealer.get("userId"),
        }

    return serialized


@router.get("/cars/{car_id}/meta")
async def public_car_meta(car_id: str):
    """
    Minimal, view-count-safe car lookup for server-side Open Graph tag
    generation only. Deliberately does NOT call the full detail
    endpoint above or its view-increment side effect - this runs on
    every page load (including social media crawlers fetching link
    previews, which don't count as real views), and reusing the
    view-incrementing endpoint here would double-count every real
    view too, since the client component fetches the full detail
    again after this metadata fetch completes.
    """
    db = get_db()
    if ObjectId.is_valid(car_id):
        car = await db["car_listings"].find_one({"_id": ObjectId(car_id), "status": {"$ne": "draft"}})
    else:
        car = await db["car_listings"].find_one({"carId": car_id, "status": {"$ne": "draft"}})

    if not car:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Car not found")

    images = car.get("images") or []
    return {
        "brand": car.get("brand"),
        "model": car.get("model"),
        "year": car.get("year"),
        "sellingPrice": car.get("sellingPrice"),
        "city": car.get("city"),
        "state": car.get("state"),
        "description": car.get("description"),
        "image": images[0] if images else None,
    }


@router.get("/search")
async def universal_search(
    q: str = Query(..., min_length=1),
    types: Optional[str] = Query(None, description="Comma-separated: cars,dealers,users. Default: all."),
    limit: int = Query(8, le=30),
):
    """
    One search box, everything on the platform: cars (by brand, model,
    year, color, or car ID), dealers (by company/owner name or city),
    and users (by name or username — covers regular users, partners,
    and buyers, since they're all in the same users collection).
    Returns a small number of results per category, meant for a quick
    "search everything" overview rather than deep pagination.
    """
    db = get_db()
    want = set((types.split(",") if types else ["cars", "dealers", "users"]))
    results: dict = {}

    if "cars" in want:
        car_or = [
            {"brand": {"$regex": q, "$options": "i"}},
            {"model": {"$regex": q, "$options": "i"}},
            {"color": {"$regex": q, "$options": "i"}},
            {"carId": {"$regex": q, "$options": "i"}},
        ]
        if q.strip().isdigit():
            car_or.append({"year": int(q.strip())})
        cars = await db["car_listings"].find(
            {"$or": car_or, "status": {"$in": ["available", "sold"]}}
        ).sort("createdAt", -1).limit(limit).to_list(limit)
        results["cars"] = [serialize_doc(c) for c in cars]

    # Common filler words in natural phrases like "looking for a
    # dealer named musa in abuja" or "dealers in lagos" — stripped so
    # only the meaningful tokens (names, locations) are required to
    # match; otherwise every filler word would also need a match and
    # the search would return nothing.
    STOPWORDS = {
        "a","an","the","for","in","at","near","around","close","to","of","on",
        "looking","find","search","show","me","is","are","he","she","they",
        "dealer","dealers","user","users","person","people","named","name","who",
    }

    if "dealers" in want:
        # Token-aware matching: split the query into words and require
        # EVERY meaningful word to match SOMEWHERE across the dealer's
        # name/city/state fields — so "musa abuja" or "looking for
        # dealer musa in abuja" correctly finds a dealer named Musa
        # located in Abuja, even though no single field contains the
        # literal phrase.
        tokens = [t for t in q.strip().split() if t and t.lower() not in STOPWORDS]
        token_conditions = [
            {"$or": [
                {"companyName": {"$regex": re.escape(tok), "$options": "i"}},
                {"ownerName": {"$regex": re.escape(tok), "$options": "i"}},
                {"city": {"$regex": re.escape(tok), "$options": "i"}},
                {"state": {"$regex": re.escape(tok), "$options": "i"}},
            ]}
            for tok in tokens
        ] or [{"companyName": {"$regex": re.escape(q), "$options": "i"}}]
        dealers = await db["dealer_organizations"].find({
            "status": "approved",
            "$and": token_conditions,
        }).limit(limit).to_list(limit)
        results["dealers"] = [serialize_doc(d) for d in dealers]

    if "users" in want:
        tokens = [t for t in q.strip().split() if t and t.lower() not in STOPWORDS]
        token_conditions = [
            {"$or": [
                {"fullName": {"$regex": re.escape(tok), "$options": "i"}},
                {"username": {"$regex": re.escape(tok), "$options": "i"}},
            ]}
            for tok in tokens
        ] or [{"fullName": {"$regex": re.escape(q), "$options": "i"}}]
        users = await db["users"].find(
            {"status": {"$ne": "suspended"}, "$and": token_conditions},
            {"passwordHash": 0},  # never expose this, even hashed
        ).limit(limit).to_list(limit)
        results["users"] = [serialize_doc(u) for u in users]

    return results


@router.post("/navigation-match")
async def navigation_match(
    payload: dict = Body(...),
    current_user: dict = Depends(get_current_user),
):
    """
    AI-backed navigation intent matching for the "tell it what you
    want to do" search — understands whatever phrasing, dialect, or
    mixed language someone uses and matches it against their own
    role's actual available pages, which the frontend sends on every
    call rather than this endpoint keeping its own possibly-stale
    copy of the app's page structure.

    Falls back to signaling unavailability rather than erroring, so
    the frontend's own local keyword/fuzzy matcher can take over
    seamlessly if the AI call isn't available for any reason.
    """
    text = (payload.get("text") or "").strip()
    entries = payload.get("entries") or []
    if not text or not entries:
        return {"available": False, "matches": [], "understood": ""}

    result = await match_navigation_with_ai(text, entries)
    if result is None:
        return {"available": False, "matches": [], "understood": ""}
    return {"available": True, **result}


@router.get("/dealers")
async def public_dealers(
    search: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(20),
):
    db = get_db()
    query = {"status": "approved"}
    if search:
        query["$or"] = [
            {"companyName": {"$regex": search, "$options": "i"}},
            {"ownerName": {"$regex": search, "$options": "i"}},
        ]
    if city:
        query["city"] = {"$regex": city, "$options": "i"}

    total = await db["dealer_organizations"].count_documents(query)
    dealers = await db["dealer_organizations"].find(query).sort(
        "totalCarsSold", -1
    ).skip(skip).limit(limit).to_list(limit)

    return {"total": total, "dealers": [serialize_doc(d) for d in dealers]}


@router.get("/dealers/{dealer_id}")
async def public_dealer_profile(dealer_id: str):
    db = get_db()
    if ObjectId.is_valid(dealer_id):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(dealer_id)})
    else:
        dealer = await db["dealer_organizations"].find_one({"dealerId": dealer_id})

    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")

    cars = await db["car_listings"].find(
        {"dealerId": str(dealer["_id"]), "status": "available"}
    ).sort("createdAt", -1).limit(20).to_list(20)

    result = serialize_doc(dealer)
    result["availableCars"] = [serialize_doc(c) for c in cars]
    result["userId"] = dealer.get("userId")
    follower_count = await db["follows"].count_documents({"dealerId": str(dealer["_id"])})
    result["followerCount"] = follower_count

    # Add social links from dealer owner's user profile if not already on dealer doc
    if dealer.get("userId"):
        owner = None
        if ObjectId.is_valid(str(dealer["userId"])):
            owner = await db["users"].find_one({"_id": ObjectId(str(dealer["userId"]))})
        if not owner:
            owner = await db["users"].find_one({"userId": str(dealer["userId"])})
        if owner:
            for field in ["instagram", "facebook", "twitter", "tiktok", "youtube", "website", "phone", "whatsapp", "email"]:
                if not result.get(field) and owner.get(field):
                    result[field] = owner.get(field)

    return result


@router.get("/dealers/{dealer_id}/meta")
async def public_dealer_meta(dealer_id: str):
    """
    Minimal lookup for server-side Open Graph tag generation only -
    same reasoning as /cars/{car_id}/meta. The full dealer profile
    endpoint above does real work a link preview never needs (fetches
    up to 20 cars, counts followers, merges owner social links) - this
    runs on every page load including crawler fetches, so keeping it
    minimal avoids that load for something that's purely cosmetic.
    """
    db = get_db()
    if ObjectId.is_valid(dealer_id):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(dealer_id)})
    else:
        dealer = await db["dealer_organizations"].find_one({"dealerId": dealer_id})

    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")

    return {
        "companyName": dealer.get("companyName"),
        "logo": dealer.get("logo"),
        "city": dealer.get("city"),
        "state": dealer.get("state"),
        "description": dealer.get("description"),
    }


#  PUBLIC USER PROFILE 
# This is what the frontend /users/[userId] page calls

@router.get("/users/{user_id}")
async def public_user_profile(user_id: str):
    db = get_db()

    # Try by ObjectId (_id) first, then by userId string
    user = None
    if ObjectId.is_valid(user_id):
        user = await db["users"].find_one({"_id": ObjectId(user_id)})
    if not user:
        user = await db["users"].find_one({"userId": user_id})

    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="User not found")

    # Return only safe public fields  never return passwordHash
    role = user.get("role", "USER")
    profile = {
        "_id": str(user["_id"]),
        "userId": str(user["_id"]),
        "fullName": user.get("fullName"),
        "role": role,
        "avatar": user.get("avatar") or user.get("profilePicture"),
        "city": user.get("city"),
        "state": user.get("state"),
        "bio": user.get("bio"),
        "phone": user.get("phone") if user.get("showPhone", True) else None,
        "whatsapp": user.get("whatsapp") if user.get("showWhatsapp", True) else None,
        "email": user.get("email") if user.get("showEmail", False) else None,
        "instagram": user.get("instagram"),
        "facebook": user.get("facebook"),
        "twitter": user.get("twitter"),
        "tiktok": user.get("tiktok"),
        "website": user.get("website"),
        "createdAt": user.get("createdAt"),
    }

    # Attach dealer info for DEALER_ADMIN and DEALER_STAFF
    if role in ("DEALER_ADMIN", "DEALER_STAFF"):
        dealer = None
        if role == "DEALER_ADMIN":
            dealer = await db["dealer_organizations"].find_one({"userId": str(user["_id"])})
        elif role == "DEALER_STAFF":
            staff = await db["staff_accounts"].find_one({"userId": str(user["_id"])})
            if staff and staff.get("dealerId"):
                dealer = await db["dealer_organizations"].find_one(
                    {"_id": ObjectId(staff["dealerId"])} if ObjectId.is_valid(staff["dealerId"])
                    else {"dealerId": staff["dealerId"]}
                )
        if dealer:
            profile["dealer"] = {
                "dealerId": dealer.get("dealerId"),
                "companyName": dealer.get("companyName"),
                "logo": dealer.get("logo"),
                "city": dealer.get("city"),
                "state": dealer.get("state"),
            }

    # Attach partner stats for PARTNER_USER
    if role == "PARTNER_USER":
        total_cars = await db["car_listings"].count_documents({"ownerId": str(user["_id"]), "ownerType": "partner"})
        total_dealers = await db["partner_links"].count_documents(
            {"partnerId": str(user["_id"]), "status": "approved"}
        ) if "partner_links" in await db.list_collection_names() else 0
        profile["stats"] = {"totalCars": total_cars, "totalDealers": total_dealers}

    return profile


@router.get("/users/{user_id}/meta")
async def public_user_meta(user_id: str):
    """
    Minimal lookup for server-side Open Graph tag generation only -
    same reasoning as the car and dealer meta endpoints. Avoids the
    dealer/partner-stats lookups the full profile endpoint above does,
    which a link preview never needs.
    """
    db = get_db()
    user = None
    if ObjectId.is_valid(user_id):
        user = await db["users"].find_one({"_id": ObjectId(user_id)})
    if not user:
        user = await db["users"].find_one({"userId": user_id})

    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "fullName": user.get("fullName"),
        "avatar": user.get("avatar") or user.get("profilePicture"),
        "city": user.get("city"),
        "state": user.get("state"),
        "bio": user.get("bio"),
    }


#  QR CODE 

@router.post("/qr/generate")
async def generate_qr(current_user: dict = Depends(get_current_dealer_or_staff)):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    frontend_url = settings.FRONTEND_URL
    return await generate_dealer_qr(dealer["_id"], frontend_url)


@router.get("/qr/me")
async def get_my_qr(current_user: dict = Depends(get_current_dealer_or_staff)):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    return await get_dealer_qr(dealer["_id"])


@router.get("/qr/{dealer_id}")
async def get_dealer_qr_public(dealer_id: str):
    return await get_dealer_qr(dealer_id)


#  LIKES 

@router.post("/cars/{car_id}/like")
async def like_car(car_id: str, current_user: dict = Depends(get_current_user)):
    return await toggle_like(str(current_user["_id"]), car_id)


@router.post("/cars/{car_id}/favorite")
async def favorite_car(car_id: str, current_user: dict = Depends(get_current_user)):
    return await add_favorite(str(current_user["_id"]), car_id)


@router.delete("/cars/{car_id}/favorite")
async def unfavorite_car(car_id: str, current_user: dict = Depends(get_current_user)):
    return await remove_favorite(str(current_user["_id"]), car_id)


@router.get("/cars/{car_id}/likes/me")
async def my_like_status(car_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    liked = await db["car_likes"].find_one({"userId": str(current_user["_id"]), "carId": car_id})
    faved = await db["favorites"].find_one({"userId": str(current_user["_id"]), "carId": car_id})
    return {"liked": bool(liked), "favorited": bool(faved)}


#  COMMENTS 

@router.post("/cars/{car_id}/comments")
async def post_comment(
    car_id: str,
    body: CommentBody,
    current_user: dict = Depends(get_current_user),
):
    return await add_comment(str(current_user["_id"]), car_id, body.text)


@router.get("/cars/{car_id}/comments")
async def list_comments(
    car_id: str,
    skip: int = Query(0),
    limit: int = Query(20),
):
    return await get_car_comments(car_id, skip, limit)


@router.delete("/cars/{car_id}/comments/{comment_id}")
async def remove_comment(
    car_id: str,
    comment_id: str,
    current_user: dict = Depends(get_current_user),
):
    is_admin = current_user.get("role") == "SYSTEM_ADMIN"
    return await delete_comment(comment_id, str(current_user["_id"]), is_admin=is_admin)



@router.get("/debug-feed")
async def debug_feed():
    """Debug: show exactly what dealers and cars the feed returns."""
    db = get_db()
    approved = await db["dealer_organizations"].find(
        {"status": "approved"}, {"_id": 1, "dealerId": 1, "companyName": 1}
    ).to_list(50)

    result = []
    for d in approved:
        str_id = str(d["_id"])
        # Count cars with string id
        cars_str = await db["car_listings"].count_documents(
            {"dealerId": str_id, "status": "available"}
        )
        # Count cars with ObjectId
        cars_oid = await db["car_listings"].count_documents(
            {"dealerId": ObjectId(str_id), "status": "available"}
        ) if ObjectId.is_valid(str_id) else 0
        # Get sample
        sample = await db["car_listings"].find(
            {"status": "available"},
            {"carId": 1, "brand": 1, "dealerId": 1}
        ).limit(3).to_list(3)

        result.append({
            "company": d.get("companyName"),
            "mongo_id": str_id,
            "dealerId_field": d.get("dealerId"),
            "cars_matching_string_id": cars_str,
            "cars_matching_objectid": cars_oid,
            "sample_cars_in_db": [
                {"carId": c.get("carId"), "dealerId": str(c.get("dealerId"))}
                for c in sample
            ],
        })

    return {"approved_dealers": result, "total_approved": len(result)}


@router.post("/cars/{car_id}/comments/{comment_id}/reply")
async def reply_comment(
    car_id: str,
    comment_id: str,
    body: ReplyBody,
    current_user: dict = Depends(get_current_user),
):
    return await add_reply(str(current_user["_id"]), comment_id, body.text)


@router.post("/cars/{car_id}/comments/{comment_id}/like")
async def like_comment(
    car_id: str,
    comment_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await toggle_comment_like(str(current_user["_id"]), comment_id)


@router.get("/cars/{car_id}/comments/likes/me")
async def my_comment_likes(
    car_id: str,
    comment_ids: str = Query(..., description="Comma-separated commentId list to check in one request"),
    current_user: dict = Depends(get_current_user),
):
    ids = [c.strip() for c in comment_ids.split(",") if c.strip()]
    liked = await get_comment_like_status(str(current_user["_id"]), ids)
    return {"liked": liked}