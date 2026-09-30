"""Server-verified Supabase identity for protected ClaimTrellis routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from claim_trellis.config import Settings
from claim_trellis.store import LOCAL_USER_ID

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthPrincipal:
    user_id: str
    is_anonymous: bool
    email: str | None = None
    email_verified: bool = False
    primary_auth_method: str | None = None
    connected_methods: tuple[str, ...] = ()


async def principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> AuthPrincipal:
    settings: Settings = request.app.state.settings
    if settings.auth_mode == "local":
        return AuthPrincipal(user_id=LOCAL_USER_ID, is_anonymous=True)
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Authentication required.")
    client: httpx.AsyncClient = request.app.state.auth_client
    try:
        response = await client.get(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/user",  # type: ignore[union-attr]
            headers={
                "apikey": settings.supabase_publishable_key or "",
                "Authorization": f"Bearer {credentials.credentials}",
            },
        )
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid session.")
        user = response.json()
        if not isinstance(user, dict):
            raise ValueError("Invalid user response")
        user_id = str(UUID(user["id"]))
        anonymous = user.get("is_anonymous") is True
        email = user.get("email")
        verified = not anonymous and isinstance(email, str) and bool(user.get("email_confirmed_at"))
        methods = (
            tuple(
                dict.fromkeys(
                    item["provider"]
                    for item in user.get("identities", [])
                    if isinstance(item, dict) and item.get("provider") in ("email", "google")
                )
            )
            if isinstance(user.get("identities"), list)
            else ()
        )
        metadata = user.get("app_metadata")
        primary = metadata.get("provider") if isinstance(metadata, dict) else None
        if primary not in ("email", "google"):
            primary = methods[0] if methods else None
        return AuthPrincipal(
            user_id=user_id,
            is_anonymous=anonymous,
            email=email if verified else None,
            email_verified=bool(verified),
            primary_auth_method=primary,
            connected_methods=methods,
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        # Never include the token or upstream response body in a public error.
        raise HTTPException(status_code=401, detail="Invalid session.") from None
