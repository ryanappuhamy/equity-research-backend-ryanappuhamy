"""
Shared slowapi rate limiter.

Kept in its own module so both api.py and the sub-routers can import the same
Limiter instance without a circular import. Storage is in-memory (fine for a
single Render instance); set RATE_LIMIT_* env vars to tune.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

import config

# headers_enabled stays False: turning it on would require every @limiter.limit
# endpoint to also declare a `response: Response` param. The 429 response still
# carries Retry-After / X-RateLimit-* via slowapi's exception handler.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[config.RATE_LIMIT_DEFAULT],
)
