"""
Optional API-key gate and helper for privileged operations.

Both mechanisms are opt-in via environment variables, so the service runs fully
open by default (local dev) and only enforces auth once configured:

    API_SECRET      -> require header  X-API-Key: <value>  on protected routes
    FORCE_PASSWORD  -> required by cache-invalidation / force-regenerate routes

SECURITY NOTE: if the browser frontend sends X-API-Key via a NEXT_PUBLIC_*
variable, that value is visible in the client bundle. It raises the bar against
drive-by scripts and bare-URL abuse; it is NOT a substitute for real per-user
auth (planned: Supabase Auth + row-level security).
"""

import hmac

from fastapi import HTTPException, Request, status

import config

# Paths that stay reachable without X-API-Key even when API_SECRET is set,
# so platform health checks and the API docs keep working.
_OPEN_PATHS = {"/health", "/docs", "/redoc", "/openapi.json", "/favicon.ico"}


async def require_api_key(request: Request) -> None:
    """FastAPI dependency: enforce X-API-Key when API_SECRET is configured."""
    if not config.API_SECRET:
        return
    if request.url.path in _OPEN_PATHS:
        return
    supplied = request.headers.get("X-API-Key", "")
    if not (supplied and hmac.compare_digest(supplied, config.API_SECRET)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
        )


def check_force_password(supplied: str | None) -> None:
    """Raise unless FORCE_PASSWORD is configured and matches the supplied value."""
    if not config.FORCE_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Force operations are disabled (FORCE_PASSWORD not set)",
        )
    if not (supplied and hmac.compare_digest(supplied, config.FORCE_PASSWORD)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized"
        )
