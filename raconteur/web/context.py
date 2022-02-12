from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional, Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import Request

from raconteur.models.game import Game
from raconteur.web.auth import AuthenticatedUser, get_authenticated_user, Permissions, get_permissions


@dataclass
class RequestContext:
    request: Request
    games: list[Game]
    current_game: Optional[Game]
    current_user: Optional[AuthenticatedUser]
    permissions: Permissions
    errors: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dict(
            request=self.request,
            games=self.games,
            current_game=self.current_game,
            current_user=self.current_user,
            permissions=self.permissions,
            errors=self.errors,
            **self.extra
        )

    @classmethod
    async def build(
            cls, session: Session, request: Request, current_game_id: Optional[int]
    ) -> RequestContext:
        games = [game for game, in session.execute(select(Game).order_by(Game.name))]
        current_game = next((game for game in games if game.guild_id == current_game_id), None)
        current_user = get_authenticated_user(request)
        all_permissions = await asyncio.gather(*[get_permissions(game, current_user) for game in games])
        accessible_games = [game for i, game in enumerate(games) if all_permissions[i].is_member]

        if current_game and current_game not in accessible_games:
            raise HTTPException(403, "You do not have access to this game.")

        return cls(
            request=request,
            games=accessible_games,
            current_game=current_game,
            current_user=current_user,
            permissions=await get_permissions(current_game, current_user),
        )
