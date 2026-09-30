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
        email = user.get("email")
        if not isinstance(email, str):
            email = None
        return AuthPrincipal(
            user_id=user_id,
            is_anonymous=user.get("is_anonymous") is True,
            email=email,
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        # Never include the token or upstream response body in a public error.
        raise HTTPException(status_code=401, detail="Invalid session.") from None
