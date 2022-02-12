import random
from enum import Enum
from typing import Optional, Union

from fastapi import APIRouter
from sqlalchemy.orm import Session

from raconteur.commands import command, CommandCallContext
from raconteur.exceptions import CommandException
from raconteur.models.base import get_session
from raconteur.plugin import Plugin
from raconteur.plugins.character.communication import send_broadcast
from raconteur.plugins.character.models import Character
from raconteur.plugins.character.plugin import get_channel_character
from raconteur.plugins.unknown_armies.models import UnknownArmiesSheet, UnknownArmiesSkill, UnknownArmiesAbility
from raconteur.plugins.unknown_armies.web import unknown_armies_router, ua_list
from raconteur.utils import fuzzy_search

STREET_LEVEL_POINTS = 220
GLOBAL_LEVEL_POINTS = 240
COSMIC_LEVEL_POINTS = 260


class SkillCheckRank(Enum):
    MINOR = "m"
    SIGNIFICANT = "s"
    MAJOR = "M"


class SkillCheckResultType(Enum):
    CRITICAL_SUCCESS = "Crit"
    SUCCESS = "Success"
    WEAK_SUCCESS = "Weak Success"
    FAILURE = "Failure"
    CRITICAL_FAILURE = "Fumble"


class UnknownArmiesPlugin(Plugin):
    @classmethod
    def assert_models(cls) -> None:
        assert Character
        assert UnknownArmiesSheet
        assert UnknownArmiesSkill

    @command(
        help_msg="Rolls a dice using your stats from your character sheet. The `stat` should be the approximate name "
                 "of the skill or attribute you are rolling with. The `rank` optionally specifies the rank of the "
                 "skill check, and can be either: `m` (minor), `s` (significant, default), `M` (major). The `shift` "
                 "applies an optional positive or negative shift.",
        requires_player=True
    )
    async def ua(
            self,
            ctx: CommandCallContext,
            stat: str,
            rank: str = SkillCheckRank.SIGNIFICANT.value,
            shift: Optional[int] = None,
    ) -> Optional[str]:
        try:
            skill_check_rank = SkillCheckRank(rank)
        except ValueError:
            raise CommandException(f"Invalid rank: `{rank}`")

        with get_session() as session:
            sheet = _get_sheet(ctx, session)
            skill, ability = _get_stat(sheet, stat)
            ability_score = sheet.get_ability_score(ability)

            result = random.randint(1, 100)
            result_str = str(result).zfill(2)
            is_matched = result_str[0] == result_str[1]
            is_fumble = result == 0
            is_crit = result == 1

            if skill:
                score = f"{skill.name} [{skill.value}]"
            else:
                score = f"{ability.value} [{ability_score}]"
            message = f"**{sheet.character.name}** rolls **{result_str}** using **{score}**"
            if shift is not None and skill is not None:
                message += f" with a skill shift of **{shift}**"
            if skill_check_rank == SkillCheckRank.MINOR:
                message += " (minor)"
            elif skill_check_rank == SkillCheckRank.SIGNIFICANT:
                message += " (significant)"
            elif skill_check_rank == SkillCheckRank.MAJOR:
                message += " (major)"
            message += ": "

            if is_fumble:
                result_type = SkillCheckResultType.CRITICAL_FAILURE
            elif is_crit:
                result_type = SkillCheckResultType.CRITICAL_SUCCESS
            elif skill_check_rank in (SkillCheckRank.MINOR, SkillCheckRank.SIGNIFICANT):
                if skill is not None:
                    if result <= skill.value + (shift or 0):
                        result_type = SkillCheckResultType.SUCCESS
                    else:
                        if skill_check_rank == SkillCheckRank.SIGNIFICANT and result <= ability_score:
                            result_type = SkillCheckResultType.WEAK_SUCCESS
                        else:
                            result_type = SkillCheckResultType.FAILURE
                else:
                    if result <= ability_score - 30:
                        result_type = SkillCheckResultType.WEAK_SUCCESS
                    else:
                        result_type = SkillCheckResultType.FAILURE
            elif skill_check_rank == SkillCheckRank.MAJOR:
                if skill is not None and result <= skill.value + (shift or 0):
                    result_type = SkillCheckResultType.SUCCESS
                elif is_matched or is_crit:
                    result_type = SkillCheckResultType.SUCCESS
                else:
                    result_type = SkillCheckResultType.FAILURE
            else:
                raise ValueError(f"Invalid rank: {skill_check_rank}")

            message += f"**{result_type.value}**"
            if is_matched and not is_fumble:
                message += " (matched)"

            if sheet.character.location:
                await send_broadcast(ctx.guild, sheet.character.location, message)
                return None
            else:
                return message

    @classmethod
    def get_web_router(cls) -> Optional[APIRouter]:
        return unknown_armies_router

    @classmethod
    def get_web_menu(cls) -> dict[str, Union[str, dict[str, str]]]:
        return {
            "Your Data": {
                "Unknown Armies": ua_list.__name__,
            },
        }


def _get_stat(
        sheet: UnknownArmiesSheet, stat: str
) -> tuple[Optional[UnknownArmiesSkill], UnknownArmiesAbility]:
    stat_lower = stat.lower()
    if stat_lower == "body":
        return None, UnknownArmiesAbility.BODY
    elif stat_lower == "speed":
        return None, UnknownArmiesAbility.SPEED
    elif stat_lower == "mind":
        return None, UnknownArmiesAbility.MIND
    elif stat_lower == "soul":
        return None, UnknownArmiesAbility.SOUL
    else:
        skills: dict[str, UnknownArmiesSkill] = {skill.name: skill for skill in sheet.skills}
        skill_name = fuzzy_search(stat, skills)
        if not skill_name:
            raise CommandException(f"Failed to locate a skill with the name `{stat}`.")
        skill = skills[skill_name]
        return skill, skill.ability


def _get_sheet(ctx: CommandCallContext, session: Session) -> UnknownArmiesSheet:
    character = get_channel_character(ctx, session)
    sheet = UnknownArmiesSheet.get_for_character(session, character.id)
    if not sheet:
        raise CommandException(
            f"Your character **{character.name}** does not have an Unknown Armies sheet."
        )
    return sheet
