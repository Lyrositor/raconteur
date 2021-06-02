from __future__ import annotations

from enum import Enum
from typing import Optional

from sqlalchemy import Column, Enum as EnumType, ForeignKey, Integer, String, Boolean, select
from sqlalchemy.orm import relationship, backref, Session

from raconteur.models.base import Base
from raconteur.plugin import PluginModelMixin
from raconteur.plugins.character.models import Character


class UnknownArmiesAbility(Enum):
    BODY = "Body"
    SPEED = "Speed"
    MIND = "Mind"
    SOUL = "Soul"


class UnknownArmiesMadness(Enum):
    VIOLENCE = "Violence"
    HELPLESSNESS = "Helplessness"
    UNNATURAL = "The Unnatural"
    ISOLATION = "Isolation"
    SELF = "Self"


class UnknownArmiesSheet(PluginModelMixin, Base):
    __plugin__ = "unknown_armies"
    __plugin_table_name__ = "sheets"

    character_id = Column(Integer, ForeignKey(Character.id), primary_key=True)
    character = relationship(
        Character, backref=backref("unknown_armies_sheet", cascade="all,delete,delete-orphan", uselist=False)
    )

    # General descriptors
    summary = Column(String, nullable=False)
    personality = Column(String, nullable=False)
    obsession = Column(String, nullable=False)
    school = Column(String)
    stimulus_fear_madness = Column(EnumType(UnknownArmiesMadness), nullable=False)
    stimulus_fear = Column(String, nullable=False)
    stimulus_rage = Column(String, nullable=False)
    stimulus_noble = Column(String, nullable=False)

    # Abilities
    body = Column(Integer, nullable=False, default=0)
    body_descriptor = Column(String, nullable=False)
    speed = Column(Integer, nullable=False, default=0)
    speed_descriptor = Column(String, nullable=False)
    mind = Column(Integer, nullable=False, default=0)
    mind_descriptor = Column(String, nullable=False)
    soul = Column(Integer, nullable=False, default=0)
    soul_descriptor = Column(String, nullable=False)

    # Skills
    xp = Column(Integer, nullable=False, default=0)
    skills = relationship(
        "UnknownArmiesSkill", back_populates="sheet", cascade="all,delete,delete-orphan", lazy="selectin"
    )

    # Madness
    violence_hardened = Column(Integer, nullable=False, default=0)
    violence_failed = Column(Integer, nullable=False, default=0)
    unnatural_hardened = Column(Integer, nullable=False, default=0)
    unnatural_failed = Column(Integer, nullable=False, default=0)
    helplessness_hardened = Column(Integer, nullable=False, default=0)
    helplessness_failed = Column(Integer, nullable=False, default=0)
    isolation_hardened = Column(Integer, nullable=False, default=0)
    isolation_failed = Column(Integer, nullable=False, default=0)
    self_hardened = Column(Integer, nullable=False, default=0)
    self_failed = Column(Integer, nullable=False, default=0)

    def get_ability_score(self, ability: UnknownArmiesAbility) -> int:
        if ability == UnknownArmiesAbility.BODY:
            return self.body
        elif ability == UnknownArmiesAbility.SPEED:
            return self.speed
        elif ability == UnknownArmiesAbility.MIND:
            return self.mind
        elif ability == UnknownArmiesAbility.SOUL:
            return self.soul
        raise ValueError(f"Invalid ability: {ability}")

    @classmethod
    def get(cls, session: Session, guild_id: int, member_id: int, character_id: int) -> Optional[UnknownArmiesSheet]:
        row = session.execute(
            select(UnknownArmiesSheet)
            .join(UnknownArmiesSheet.character)
            .where(
                UnknownArmiesSheet.game_guild_id == guild_id,
                Character.id == character_id,
                Character.member_id == member_id
            )
        ).one_or_none()
        return row[0] if row else None

    @classmethod
    def get_all_of_member(cls, session: Session, guild_id: int, member_id: int) -> list[UnknownArmiesSheet]:
        return [
            sheet for sheet, in session.execute(
                select(UnknownArmiesSheet)
                .join(UnknownArmiesSheet.character)
                .where(UnknownArmiesSheet.game_guild_id == guild_id, Character.member_id == member_id)
            )
        ]

    @classmethod
    def get_for_character(cls, session: Session, character_id: int) -> Optional[UnknownArmiesSheet]:
        row = session.execute(
            select(UnknownArmiesSheet).where(UnknownArmiesSheet.character_id == character_id)
        ).one_or_none()
        return row[0] if row else None


class UnknownArmiesSkill(PluginModelMixin, Base):
    __plugin__ = "unknown_armies"
    __plugin_table_name__ = "skills"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    value = Column(Integer, nullable=False, default=0)
    ability = Column(EnumType(UnknownArmiesAbility), nullable=False)
    is_obsession = Column(Boolean, nullable=False, default=False)

    sheet_id = Column(Integer, ForeignKey(UnknownArmiesSheet.character_id), nullable=False)
    sheet = relationship(UnknownArmiesSheet, back_populates="skills")
