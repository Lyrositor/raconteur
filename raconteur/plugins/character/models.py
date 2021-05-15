from __future__ import annotations

from typing import Optional

from sqlalchemy import String, Column, Integer, ForeignKey, DateTime, Boolean, select
from sqlalchemy.orm import relationship, Session

from raconteur.models.base import Base
from raconteur.plugin import PluginModelMixin

CHARACTER_NAME_MAX_LENGTH = 60
CHARACTER_STATUS_MAX_LENGTH = 200
CHARACTER_APPEARANCE_MAX_LENGTH = 1000
LOCATION_NAME_MAX_LENGTH = 60
LOCATION_CATEGORY_MAX_LENGTH = 60
LOCATION_DESCRIPTION_MAX_LENGTH = 1500


class Location(PluginModelMixin, Base):
    __plugin__ = "character"
    __plugin_table_name__ = "locations"

    id = Column(Integer, primary_key=True)
    name = Column(String(LOCATION_NAME_MAX_LENGTH), nullable=False)
    category = Column(String(LOCATION_CATEGORY_MAX_LENGTH), nullable=False)
    description = Column(String(LOCATION_DESCRIPTION_MAX_LENGTH), nullable=False)
    channel_id = Column(Integer, unique=True)
    characters = relationship("Character", back_populates="location")
    connections_1 = relationship(
        "Connection", back_populates="location_1", foreign_keys="Connection.location_1_id", cascade="all, delete-orphan"
    )
    connections_2 = relationship(
        "Connection", back_populates="location_2", foreign_keys="Connection.location_2_id", cascade="all, delete-orphan"
    )

    @property
    def connections(self) -> list[Connection]:
        return list(self.connections_1 + self.connections_2)

    @classmethod
    def get(cls, session: Session, guild_id: int, location_id: int) -> Optional[Location]:
        row = session.execute(select(Location).where(
            Location.game_guild_id == guild_id, Location.id == location_id,
        )).one_or_none()
        return row[0] if row else None

    @classmethod
    def get_by_name(cls, session: Session, guild_id: int, name: str) -> Optional[Location]:
        row = session.execute(select(Location).where(
            Location.game_guild_id == guild_id, Location.name == name,
        )).one_or_none()
        return row[0] if row else None

    @classmethod
    def get_for_channel(cls, session: Session, guild_id: int, channel_id: int) -> Optional[Location]:
        row = session.execute(select(Location).where(
            Location.game_guild_id == guild_id, Location.channel_id == channel_id,
        )).one_or_none()
        return row[0] if row else None

    @classmethod
    def get_all(cls, session: Session, guild_id: int) -> list[Location]:
        return [
            location for location, in session.execute(select(Location).where(Location.game_guild_id == guild_id))
        ]


class Connection(PluginModelMixin, Base):
    __plugin__ = "character"
    __plugin_table_name__ = "connections"

    id = Column(Integer, primary_key=True)
    timer = Column(Integer, nullable=False, default=0)
    locked = Column(Boolean, nullable=False, default=False)
    hidden = Column(Boolean, nullable=False, default=False)
    location_1_id = Column(Integer, ForeignKey(Location.id), nullable=False)
    location_1 = relationship(Location, lazy="selectin", foreign_keys=location_1_id)
    location_2_id = Column(Integer, ForeignKey(Location.id), nullable=False)
    location_2 = relationship(Location, lazy="selectin", foreign_keys=location_2_id)


class Character(PluginModelMixin, Base):
    __plugin__ = "character"
    __plugin_table_name__ = "characters"

    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, nullable=False)
    name = Column(String(CHARACTER_NAME_MAX_LENGTH), nullable=False)
    status = Column(String(CHARACTER_STATUS_MAX_LENGTH))
    appearance = Column(String(CHARACTER_APPEARANCE_MAX_LENGTH))
    portrait = Column(String)
    channel_id = Column(Integer, unique=True)
    last_movement = Column(DateTime)
    intercept = Column(Boolean, default=False, nullable=False)
    location_id = Column(Integer, ForeignKey(Location.id), nullable=True)
    location = relationship(Location, back_populates="characters", uselist=False)

    @classmethod
    def get(cls, session: Session, guild_id: int, member_id: int, character_id: int) -> Optional[Character]:
        row = session.execute(select(Character).where(
            Character.game_guild_id == guild_id, Character.member_id == member_id, Character.id == character_id,
        )).one_or_none()
        return row[0] if row else None

    @classmethod
    def get_by_id(cls, session: Session, guild_id: int, character_id: int) -> Optional[Character]:
        row = session.execute(select(Character).where(
            Character.game_guild_id == guild_id, Character.id == character_id,
        )).one_or_none()
        return row[0] if row else None

    @classmethod
    def get_by_name(cls, session: Session, guild_id: int, name: str) -> Optional[Character]:
        row = session.execute(select(Character).where(
            Character.game_guild_id == guild_id, Character.name == name,
        )).one_or_none()
        return row[0] if row else None

    @classmethod
    def get_by_name_and_member(cls, session: Session, guild_id: int, member_id: int, name: str) -> Optional[Character]:
        row = session.execute(select(Character).where(
            Character.game_guild_id == guild_id, Character.member_id == member_id, Character.name == name,
        )).one_or_none()
        return row[0] if row else None

    @classmethod
    def get_all_of_member(cls, session: Session, guild_id: int, member_id: int) -> list[Character]:
        return [
            character for character, in session.execute(select(Character).where(
                Character.game_guild_id == guild_id, Character.member_id == member_id
            ))
        ]

    @classmethod
    def get_all_of_guild(cls, session: Session, guild_id: int) -> list[Character]:
        return [
            character for character, in session.execute(select(Character).where(Character.game_guild_id == guild_id))
        ]

    @classmethod
    def get_for_channel(cls, session: Session, channel_id: int, member_id: int) -> Optional[Character]:
        row = session.execute(select(Character).where(
            Character.channel_id == channel_id, Character.member_id == member_id
        )).one_or_none()
        return row[0] if row else None
