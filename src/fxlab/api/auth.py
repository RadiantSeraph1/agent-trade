"""Verify the signed header injected by Cloud Run's Identity-Aware Proxy.

Fails closed: missing/invalid JWT, unset audience, or an email outside the
allowlist is rejected. We verify IAP's signature rather than trusting the
plain email header.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Callable

from fastapi import HTTPException, Request

from fxlab.config import Settings

log = logging.getLogger("fxlab.auth")
IAP_CERTS = "https://www.gstatic.com/iap/verify/public_key"
IAP_ISSUER = "https://cloud.google.com/iap"
IAP_HEADER = "x-goog-iap-jwt-assertion"


def _verify_iap(token: str, audience: str) -> dict:
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token

    claims = id_token.verify_token(token, g_requests.Request(), audience=audience, certs_url=IAP_CERTS)
    if claims.get("iss") != IAP_ISSUER:
        raise ValueError("bad issuer")
    return claims


def _unverified_aud(token: str) -> str | None:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("aud")
    except Exception:
        return None


def make_current_user(settings: Settings, verify: Callable[[str, str], dict] = _verify_iap):
    allowed = {e.strip().lower() for e in settings.allowed_emails if e.strip()}

    def current_user(request: Request) -> str:
        token = request.headers.get(IAP_HEADER, "")
        if not token:
            raise HTTPException(status_code=401, detail="missing IAP assertion")
        if not settings.iap_audience:
            # One-off discovery aid: the audience is not a secret. Never log the token.
            log.warning("IAP audience not configured; token aud claim is %r", _unverified_aud(token))
            raise HTTPException(status_code=503, detail="auth not configured")
        try:
            claims = verify(token, settings.iap_audience)
        except Exception:
            raise HTTPException(status_code=401, detail="invalid IAP assertion") from None
        email = str(claims.get("email", "")).lower()
        if email not in allowed:
            raise HTTPException(status_code=403, detail="not allowed")
        return email

    return current_user
