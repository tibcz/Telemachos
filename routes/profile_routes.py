# routes/profile_routes.py
"""Who is using this copy of the app.

Telemachos is single-user, so there is no account to sign into and nothing to
authenticate. This is a display identity: a name and an avatar, seeded from the
macOS account on first run and editable afterwards. See src/user_profile.py.
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.auth_helpers import require_user

logger = logging.getLogger(__name__)


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=60)
    color: str | None = None


def setup_profile_routes() -> APIRouter:
    router = APIRouter(prefix="/api/profile", tags=["profile"])

    @router.get("")
    async def read_profile(request: Request):
        require_user(request)
        import src.user_profile as profile

        from src.owner_identity import auth_disabled

        # The client hides the password / two-factor / sign-out controls when
        # there is no authentication behind them. Leaving dead buttons on
        # screen is what made the account panel feel broken.
        return {
            **profile.load(),
            "colors": profile.AVATAR_COLORS,
            "auth_enabled": not auth_disabled(),
        }

    @router.put("")
    async def write_profile(body: ProfileUpdate, request: Request):
        require_user(request)
        import src.user_profile as profile

        try:
            return profile.save(body.display_name, color=body.color)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    return router
