from __future__ import annotations

from typing import Union, Type, Optional

from sqlalchemy import Integer, Column, ForeignKey, String
from sqlalchemy.orm import relationship
from sqlalchemy_json import NestedMutableJson

from raconteur.models.base import Base


class Game(Base):
    __tablename__ = "games"

    guild_id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    plugins = relationship("GamePlugin", back_populates="game", cascade="all, delete-orphan", lazy="selectin")
    gm_role_id = Column(Integer, nullable=True)
    player_role_id = Column(Integer, nullable=True)
    spectator_role_id = Column(Integer, nullable=True)

    def get_plugin(self, name: Union[Type, str]) -> Optional[GamePlugin]:
        if not isinstance(name, str):
            name = name.__name__
        for plugin in self.plugins:
            if plugin.name == name:
                return plugin
        return None


class GamePlugin(Base):
    __tablename__ = "games_plugins"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    settings = Column(NestedMutableJson, default=lambda: {}, nullable=False)
    game_guild_id = Column(Integer, ForeignKey(Game.guild_id), nullable=False)
    game = relationship(Game, back_populates="plugins")
