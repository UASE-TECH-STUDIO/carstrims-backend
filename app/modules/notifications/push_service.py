"""
CARSTRIMS Push Notification Service
- Web Push (VAPID/pywebpush) for web browsers
- Firebase FCM V1 API for Android/iOS apps (Service Account auth)
"""
import json
import asyncio
from datetime import datetime
from app.database.connection import get_db
from app.config.settings import settings


#  WEB PUSH (VAPID) 

def _send_push_sync(subscription_info: dict, payload: str, vapid_private_key: str, vapid_claims: dict):
    """Synchronous pywebpush call - runs in thread pool."""
    from pywebpush import webpush, WebPushException
    webpush(
        subscription_info=subscription_info,
        data=payload,
        vapid_private_key=vapid_private_key,
        vapid_claims=vapid_claims,
        ttl=86400,
    )


async def send_web_push_to_user(
    user_id: str,
    title: str,
    body: str,
    url: str = "/dashboard",
    icon: str = "/icon-192.png",
) -> int:
    """Send a push notification to a user - both Web Push (VAPID, for
    browser tabs with an active subscription) and native FCM (for the
    Android/iOS app, via device_tokens) run together here.

    This function's name and signature are unchanged from before, but
    its actual behavior was previously Web Push only - it is imported
    and called under this exact name from 30+ places across the
    backend (follows, dealers, admin, users, movements, partners,
    messages, notify.py), every one of which assumed calling this
    reached "the user", not just "the user's open browser tabs". A
    separate, correctly-built send_fcm_push_to_user already existed
    lower in this file and worked correctly against the device_tokens
    the native app registers (see CapacitorPush.tsx) - nothing had
    ever actually called it. Merging the FCM send in here, under the
    name every caller already uses, fixes every one of those 30+ call
    sites at once with no caller-side changes needed, rather than
    editing each individually.
    """
    results = await asyncio.gather(
        _send_web_push_only(user_id, title, body, url, icon),
        send_fcm_push_to_user(user_id, title, body, url),
        return_exceptions=True,
    )
    return sum(r for r in results if isinstance(r, int))


async def _send_web_push_only(
    user_id: str,
    title: str,
    body: str,
    url: str = "/dashboard",
    icon: str = "/icon-192.png",
) -> int:
    """The original Web Push (VAPID) implementation, unchanged -
    renamed so send_web_push_to_user above can call it as one half of
    a combined send while keeping its own name and signature stable
    for the 30+ existing callers."""
    if not user_id:
        return 0

    vapid_private = getattr(settings, "VAPID_PRIVATE_KEY", "").strip()
    if not vapid_private:
        return 0

    db = get_db()
    subs = await db["push_subscriptions"].find({"userId": user_id}).to_list(20)
    if not subs:
        return 0

    payload = json.dumps({
        "title":   title,
        "message": body,
        "body":    body,
        "url":     url,
        "icon":    icon,
        "badge":   "/icon-72.png",
        "sound":   True,
        "tag":     f"carstrims-{user_id[:8]}-{title[:10]}",
        "vibrate": [200, 100, 200],
    })

    sent = 0
    loop = asyncio.get_event_loop()
    for sub in subs:
        try:
            sub_info = sub.get("subscription") or sub
            endpoint = sub_info.get("endpoint", "")
            if not endpoint:
                continue

            aud = "/".join(endpoint.split("/")[:3])
            claims = {"sub": "mailto:support@carstrims.com", "aud": aud}

            await loop.run_in_executor(
                None, _send_push_sync, sub_info, payload, vapid_private, claims
            )
            sent += 1
        except Exception as e:
            err = str(e)
            if "410" in err or "404" in err or "unsubscribed" in err.lower():
                await db["push_subscriptions"].delete_one({"_id": sub["_id"]})
    return sent


#  FCM V1 API (Android / iOS app) 

async def _get_fcm_access_token() -> str:
    """Get short-lived OAuth2 token from Firebase Service Account JSON."""
    sa_json = getattr(settings, "FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if not sa_json:
        return ""
    try:
        import json as _json
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as _GReq

        creds_dict = _json.loads(sa_json)
        scopes = ["https://www.googleapis.com/auth/firebase.messaging"]
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=scopes)
        creds.refresh(_GReq())
        return creds.token or ""
    except Exception as e:
        print(f"[FCM] Failed to get access token: {e}")
        return ""


async def send_fcm_push_to_user(
    user_id: str,
    title: str,
    body: str,
    url: str = "/dashboard",
) -> int:
    """Send FCM V1 push to all registered Android/iOS devices for a user."""
    project_id = getattr(settings, "FIREBASE_PROJECT_ID", "").strip()
    if not project_id:
        return 0

    token = await _get_fcm_access_token()
    if not token:
        return 0

    db = get_db()
    devices = await db["device_tokens"].find({"userId": user_id}).to_list(20)
    if not devices:
        return 0

    import httpx
    sent = 0
    fcm_url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

    for dev in devices:
        fcm_token = dev.get("token", "")
        if not fcm_token:
            continue
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    fcm_url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "message": {
                            "token": fcm_token,
                            "notification": {
                                "title": title,
                                "body": body,
                            },
                            "android": {
                                "priority": "high",
                                "notification": {
                                    "icon": "ic_launcher",
                                    "color": "#F47B20",
                                    "sound": "default",
                                    "channel_id": "carstrims_default",
                                    "click_action": "FLUTTER_NOTIFICATION_CLICK",
                                },
                            },
                            "data": {
                                "url": url,
                                "title": title,
                                "body": body,
                            },
                        }
                    },
                )
                if resp.status_code == 200:
                    sent += 1
                elif resp.status_code in (400, 404):
                    # Invalid/expired token - remove it
                    err = resp.json()
                    if "UNREGISTERED" in str(err) or "INVALID_ARGUMENT" in str(err):
                        await db["device_tokens"].delete_one({"_id": dev["_id"]})
                else:
                    print(f"[FCM] Error {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"[FCM] Send error: {e}")

    return sent


async def send_push_to_user(
    user_id: str,
    title: str,
    body: str,
    url: str = "/dashboard",
    icon: str = "/icon-192.png",
) -> int:
    """Alias for send_web_push_to_user, which - despite its name -
    already sends both Web Push and native FCM together (see its own
    docstring for why). Kept as a separate, more accurately-named
    entry point for any future caller who'd otherwise reasonably
    expect a function literally named send_web_push_to_user to be
    web-only."""
    return await send_web_push_to_user(user_id, title, body, url, icon)
