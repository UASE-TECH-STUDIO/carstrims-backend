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
    """Send Web Push (VAPID) to all subscribed browsers for a user."""
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
    """Send push to a user via BOTH web push AND FCM app push simultaneously."""
    results = await asyncio.gather(
        send_web_push_to_user(user_id, title, body, url, icon),
        send_fcm_push_to_user(user_id, title, body, url),
        return_exceptions=True,
    )
    return sum(r for r in results if isinstance(r, int))
