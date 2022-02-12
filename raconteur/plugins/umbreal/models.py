from __future__ import annotations

from enum import Enum
from typing import Optional, Iterable

from sqlalchemy import Column, Enum as EnumType, Integer, ForeignKey, String, select
from sqlalchemy.orm import relationship, backref, Session

from raconteur.models.base import Base
from raconteur.plugin import PluginModelMixin
from raconteur.plugins.character.models import Character


class UmbrealTraitSet(Enum):
    DISTINCTIONS = "Distinctions"
    ATTRIBUTES = "Attributes"
    SKILLS = "Skills"
    POWERS = "Powers"
    SIGNATURE_ASSETS = "Signature Assets"
    ASSETS = "Assets"
    COMPLICATIONS = "Complications"


class UmbrealSheet(PluginModelMixin, Base):
    __plugin__ = "umbreal"
    __plugin_table_name__ = "sheets"

    character_id = Column(Integer, ForeignKey(Character.id), primary_key=True)
    character = relationship(
        Character, backref=backref("umbreal_sheet", cascade="all,delete,delete-orphan", uselist=False)
    )

    plot_points = Column(Integer, nullable=False, default=0)
    xp_current = Column(Integer, nullable=False, default=0)
    xp_lifetime = Column(Integer, nullable=False, default=0)
    xp_1_milestone = Column(String, nullable=False, default="")
    xp_3_milestone = Column(String, nullable=False, default="")
    xp_10_milestone = Column(String, nullable=False, default="")

    traits: list[UmbrealTrait] = relationship(
        "UmbrealTrait", back_populates="sheet", cascade="all,delete,delete-orphan", lazy="selectin"
    )
    lawbreaks: list[UmbrealLawbreak] = relationship(
        "UmbrealLawbreak", back_populates="sheet", cascade="all,delete,delete-orphan", lazy="selectin"
    )

    @property
    def distinctions(self) -> list[UmbrealTrait]:
        return [trait for trait in self.traits if trait.set == UmbrealTraitSet.DISTINCTIONS]

    @property
    def attributes(self) -> list[UmbrealTrait]:
        return _sorted_assets(self.traits, UmbrealTraitSet.ATTRIBUTES)

    @property
    def skills(self) -> list[UmbrealTrait]:
        return _sorted_assets(self.traits, UmbrealTraitSet.SKILLS)

    @property
    def powers(self) -> list[UmbrealTrait]:
        return _sorted_assets(self.traits, UmbrealTraitSet.POWERS)

    @property
    def assets(self) -> list[UmbrealTrait]:
        signature_assets = _sorted_assets(self.traits, UmbrealTraitSet.SIGNATURE_ASSETS)
        temporary_assets = _sorted_assets(self.traits, UmbrealTraitSet.ASSETS)
        return signature_assets + temporary_assets

    @classmethod
    def get(cls, session: Session, guild_id: int, member_id: int, character_id: int) -> Optional[UmbrealSheet]:
        row = session.execute(
            select(UmbrealSheet)
            .join(UmbrealSheet.character)
            .where(
                UmbrealSheet.game_guild_id == guild_id,
                Character.id == character_id,
                Character.member_id == member_id
            )
        ).one_or_none()
        return row[0] if row else None

    @classmethod
    def get_all_of_guild(cls, session: Session, guild_id: int) -> list[UmbrealSheet]:
        return [
            sheet for sheet, in session.execute(
                select(UmbrealSheet)
                .join(UmbrealSheet.character)
                .where(UmbrealSheet.game_guild_id == guild_id)
            )
        ]

    @classmethod
    def get_all_of_member(cls, session: Session, guild_id: int, member_id: int) -> list[UmbrealSheet]:
        return [
            sheet for sheet, in session.execute(
                select(UmbrealSheet)
                .join(UmbrealSheet.character)
                .where(UmbrealSheet.game_guild_id == guild_id, Character.member_id == member_id)
            )
        ]

    @classmethod
    def get_for_character(cls, session: Session, character_id: int) -> Optional[UmbrealSheet]:
        row = session.execute(
            select(UmbrealSheet).where(UmbrealSheet.character_id == character_id)
        ).one_or_none()
        return row[0] if row else None


class UmbrealTrait(PluginModelMixin, Base):
    __plugin__ = "umbreal"
    __plugin_table_name__ = "traits"

    id = Column(Integer, primary_key=True)
    set = Column(EnumType(UmbrealTraitSet), nullable=False)
    name = Column(String, nullable=False)
    value = Column(Integer, nullable=False, default=0)
    description = Column(String, nullable=False)

    sheet_id = Column(Integer, ForeignKey(UmbrealSheet.character_id), nullable=False)
    sheet = relationship(UmbrealSheet, back_populates="traits")

    @property
    def rating(self) -> Optional[int]:
        if not self.value:
            return None
        return 2 + self.value * 2


class UmbrealLawbreak(PluginModelMixin, Base):
    __plugin__ = "umbreal"
    __plugin_table_name__ = "lawbreaks"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False)

    sheet_id = Column(Integer, ForeignKey(UmbrealSheet.character_id), nullable=False)
    sheet = relationship(UmbrealSheet, back_populates="lawbreaks")


def _sorted_assets(traits: Iterable[UmbrealTrait], trait_set: UmbrealTraitSet) -> list[UmbrealTrait]:
    return sorted((trait for trait in traits if trait.set == trait_set), key=lambda t: t.name)
