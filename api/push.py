"""Web Push (RFC 8292 VAPID): completion notifications with zero external services.

No push-provider account or API key needed -- every browser's own built-in
push service (Chrome/Edge -> FCM, Firefox -> Mozilla's push service, etc.)
accepts a payload signed with a VAPID keypair directly. The keypair is
generated once and persisted to disk, same pattern api/db.py uses for the
SQLite file, so it survives a restart with no setup step and, critically,
without invalidating every subscription a browser already granted (a
subscription is bound to the public key it was created against; issuing a
fresh key on every restart would silently break notifications for anyone
who granted permission before the last one).
"""

from __future__ import annotations

import json
import logging
import os

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02
from py_vapid.utils import b64urlencode
from pywebpush import WebPushException, webpush

logger = logging.getLogger("api.push")

_vapid: Vapid02 | None = None


def _keys_path() -> str:
    home = os.path.join(os.path.expanduser("~"), ".tradingagents")
    os.makedirs(home, exist_ok=True)
    return os.path.join(home, "vapid_private_key.pem")


def get_vapid() -> Vapid02:
    """The process-wide VAPID keypair. Cached in-process; persisted to disk
    across restarts."""
    global _vapid
    if _vapid is not None:
        return _vapid

    path = _keys_path()
    if os.path.exists(path):
        with open(path, "rb") as f:
            _vapid = Vapid02.from_pem(f.read())
    else:
        _vapid = Vapid02()
        _vapid.generate_keys()
        with open(path, "wb") as f:
            f.write(_vapid.private_pem())
    return _vapid


def public_key_b64() -> str:
    """The raw, URL-safe-base64 uncompressed EC point the browser's
    ``PushManager.subscribe({applicationServerKey: ...})`` expects. NOT the
    same encoding as the persisted private key's PEM file."""
    vapid = get_vapid()
    raw_point = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return b64urlencode(raw_point)


def send(subscription_info: dict, payload: dict, vapid_subject: str) -> bool:
    """Send one push notification. Returns whether it succeeded.

    Never raises. A push failure -- an expired subscription (the browser
    revoked it, the device is offline for good, the endpoint 410s) or a
    transient network error -- must never fail or even slow down the run it
    is reporting on. The run has already reached its terminal state by the
    time this is called; the notification is a courtesy on top of it, not
    part of it.
    """
    vapid = get_vapid()
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=vapid,
            vapid_claims={"sub": vapid_subject},
        )
        return True
    except WebPushException as exc:
        logger.warning("push send failed: %s", exc)
        return False
    except Exception as exc:  # noqa: BLE001 - never let a push glitch touch the run
        logger.warning("push send failed unexpectedly: %s", exc)
        return False
