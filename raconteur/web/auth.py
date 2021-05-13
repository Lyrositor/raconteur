from typing import Any, Optional

from aiocached import cached
from authlib.integrations.starlette_client import OAuth, StarletteRemoteApp
from fastapi import APIRouter
from loginpass import Discord
from loginpass.discord import normalize_userinfo
from pydantic import BaseModel
from starlette.config import Config as StarletteConfig
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from raconteur.config import config
from raconteur.models.game import Game
from raconteur.web.client import get_client
from raconteur.web.loginpass_ext import create_fastapi_routes


class AuthenticatedUser(BaseModel):
    id: int
    username: str
    email: str


class Permissions(BaseModel):
    is_gm: bool
    is_player: bool
    is_spectator: bool


def get_authenticated_user(request: Request) -> Optional[AuthenticatedUser]:
    user_data = request.session.get("user")
    return AuthenticatedUser.parse_obj(user_data) if user_data else None


async def get_permissions(
        game: Optional[Game], user: Optional[AuthenticatedUser]
) -> Permissions:
    permissions = Permissions(
        is_gm=False,
        is_player=False,
        is_spectator=False,
    )
    if game is not None and user is not None:
        role_ids = await _get_member_roles(game.guild_id, user.id)
        permissions.is_gm = game.gm_role_id in role_ids
        permissions.is_player = game.player_role_id in role_ids
        permissions.is_spectator = game.spectator_role_id in role_ids
    return permissions


async def async_normalize_info(client: Any, data: Any) -> dict[str, Any]:
    # Fix for async apps: authlib expects an async function, but the Discord integration doesn't provide that
    return normalize_userinfo(client, data)


async def handle_authorize(
        remote: StarletteRemoteApp, token: Optional[str], user_info: Optional[dict[str, Any]], request: Request
) -> Response:
    request.session["user"] = None
    if user_info:
        user = AuthenticatedUser(id=int(user_info["sub"]), username=user_info["name"], email=user_info["email"])
        request.session["user"] = user.dict()
    return RedirectResponse(request.url_for("home"))


async def logout(request: Request) -> RedirectResponse:
    request.session["user"] = None
    return RedirectResponse(request.url_for("home"))


def get_auth_router() -> APIRouter:
    oauth_config = StarletteConfig(
        environ={"DISCORD_CLIENT_ID": config.bot_client_id, "DISCORD_CLIENT_SECRET": config.bot_client_secret}
    )
    oauth = OAuth(oauth_config)
    Discord.OAUTH_CONFIG["userinfo_compliance_fix"] = async_normalize_info
    router = create_fastapi_routes([Discord], oauth, handle_authorize)
    router.add_api_route("/logout", logout)
    return router


@cached(ttl=60)
async def _get_member_roles(guild_id: int, user_id: int) -> list[int]:
    client = await get_client()
    user = await client.http.get_member(guild_id, user_id)
    return [int(role_id) for role_id in user["roles"]]
