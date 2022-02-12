import asyncio
import itertools
import re
from dataclasses import dataclass, field
from random import randint
from typing import Optional, Union, Iterable

from discord import Reaction, Member, TextChannel, Message
from fastapi import APIRouter
from sqlalchemy.orm import Session

from raconteur.commands import command, CommandCallContext
from raconteur.exceptions import CommandException
from raconteur.messages import send_message
from raconteur.models.base import get_session
from raconteur.plugin import Plugin, get_permissions_for_member
from raconteur.plugins.character.plugin import get_channel_character
from raconteur.plugins.umbreal.models import UmbrealSheet, UmbrealTraitSet, UmbrealTrait
from raconteur.plugins.umbreal.web import umbreal_router, umbreal_list
from raconteur.utils import fuzzy_search

DICE_ROLL_PATTERN = re.compile(r"(?P<num>\d+)?d(?P<rating>\d+)")
TRAIT_ROLL_PATTERN = re.compile(r"(?P<character>.+?)?!(?P<trait>.+)")
PLAYER_VALID_TRAIT_SETS = {
    UmbrealTraitSet.ASSETS,
    UmbrealTraitSet.ATTRIBUTES,
    UmbrealTraitSet.DISTINCTIONS,
    UmbrealTraitSet.POWERS,
    UmbrealTraitSet.SIGNATURE_ASSETS,
    UmbrealTraitSet.SKILLS,
}
OTHER_VALID_TRAIT_SETS = {UmbrealTraitSet.COMPLICATIONS}
VALID_DICE_RATINGS = {4, 6, 8, 10, 12}

MAX_CHOICES = 15


@dataclass
class DiceResult:
    name: str
    rating: int
    value: int


@dataclass(eq=True, frozen=True)
class RollChoice:
    total: int
    effect: int

    def __lt__(self, other: "RollChoice") -> bool:
        if self.total < other.total:
            return True
        if self.effect < other.effect:
            return True
        return False

    def __str__(self) -> str:
        return f"**{self.total}** (:d{self.effect}:)"


@dataclass
class Side:
    member_id: Optional[int] = None
    user_name: Optional[str] = None
    options: list[RollChoice] = field(default_factory=list)
    message_id: Optional[int] = None
    rolls: list[DiceResult] = field(default_factory=list)
    choice: Optional[RollChoice] = None


@dataclass
class Test:
    name: str
    difficulty: Side = field(default_factory=lambda: Side())
    player: Side = field(default_factory=lambda: Side())


class UmbrealPlugin(Plugin):
    ongoing_tests: dict[str, Test]
    ongoing_contests: dict  # TODO

    @classmethod
    def assert_models(cls) -> None:
        assert UmbrealSheet

    def __init__(self, bot):
        super().__init__(bot)
        self.ongoing_tests = {}
        self.ongoing_contests = {}

    async def on_reaction_add(self, reaction: Reaction, user: Member) -> None:
        emoji = reaction.emoji if isinstance(reaction.emoji, str) else reaction.emoji.name
        for option_idx in range(MAX_CHOICES):
            if _get_unicode_emoji_for_choice(option_idx) == emoji:
                break
        else:
            # Not a choice emoji
            return
        channel = reaction.message.channel
        for test in self.ongoing_tests.values():
            try:
                if test.difficulty.message_id == reaction.message.id:
                    await _set_test_difficulty_choice(channel, test, test.difficulty.options[option_idx])
                    break
                if test.player.message_id == reaction.message.id:
                    await _set_test_player_choice(channel, test, test.player.options[option_idx])
                    del self.ongoing_tests[test.name]
                    break
            except IndexError:
                break

    @command(
        help_msg="Runs a named Cortex Prime test. If a test with that name doesn't exist, this roll sets the "
                 "difficulty; otherwise, the roll tries to beat the difficulty that was previously set.",
        requires_player=True
    )
    async def test(self, ctx: CommandCallContext, name: str, *traits: str) -> None:
        with get_session() as session:
            if name not in self.ongoing_tests:
                self.ongoing_tests[name] = Test(name=name)
                await _roll_for_test_side(ctx, session, self.ongoing_tests[name].difficulty, traits)
            elif self.ongoing_tests[name].difficulty.choice:
                await _roll_for_test_side(
                    ctx,
                    session,
                    self.ongoing_tests[name].player,
                    traits,
                    self.ongoing_tests[name].difficulty.choice.total
                )
            else:
                raise CommandException(
                    "You need to set choose a roll result, either by reacting to the results list or by using "
                    "`.testset`."
                )

    @command(
        help_msg="Manually sets the result of a named test, if a custom arrangement is desired.",
        requires_player=True
    )
    async def test_set(self, ctx: CommandCallContext, name: str, total: int, effect: int) -> None:
        if name not in self.ongoing_tests:
            raise CommandException(f"There is no test with the name: {name}")
        test = self.ongoing_tests[name]
        choice = RollChoice(total=total, effect=effect)
        if not test.difficulty.choice:
            await _set_test_difficulty_choice(ctx.channel, test, choice)
            return
        await _set_test_player_choice(ctx.channel, test, choice)
        del self.ongoing_tests[name]

    @command(
        help_msg="Hands out XP to the specified character.",
        requires_gm=True
    )
    async def xp(self, ctx: CommandCallContext, character: str, amount: int) -> str:
        pass

    @classmethod
    def get_web_router(cls) -> Optional[APIRouter]:
        return umbreal_router

    @classmethod
    def get_web_menu(cls) -> dict[str, Union[str, dict[str, str]]]:
        return {
            "Your Data": {
                "Umbreal": umbreal_list.__name__,
            },
        }


async def _set_test_difficulty_choice(channel: TextChannel, test: Test, choice: RollChoice) -> None:
    test.difficulty.choice = choice
    await send_message(
        channel,
        f"**{test.difficulty.user_name}** sets the difficulty for `{test.name}` to {test.difficulty.choice}."
    )
    react_message: Message = await channel.fetch_message(test.difficulty.message_id)
    await asyncio.gather(
        react_message.edit(content=react_message.content.split("\n")[0]),
        react_message.clear_reactions()
    )


async def _set_test_player_choice(channel: TextChannel, test: Test, choice: RollChoice) -> None:
    test.player.choice = choice
    message = f"**{test.player.user_name}** sets their roll for `{test.name}` to {test.player.choice}."
    diff = test.player.choice.total - test.difficulty.choice.total
    if diff >= 5:
        step_ups = int(diff / 5)
        new_effect = min(test.player.choice.effect + step_ups * 2, 12)
        message = f"This is a **heroic success**. The effect die is stepped up to :d{new_effect}:."
    elif diff > 0:
        message = f"This is a **success** with effect :d{test.player.choice.effect}:."
    else:
        message += "This is a **failure**."
    await send_message(channel, message)

    react_message: Message = await channel.fetch_message(test.player.message_id)
    await asyncio.gather(
        react_message.edit(content=react_message.content.split("\n")[0]),
        react_message.clear_reactions()
    )


async def _roll_for_test_side(
    ctx: CommandCallContext, session: Session, side: Side, trait_names: Iterable[str], difficulty: Optional[int] = None
) -> None:
    side.member_id = ctx.member.id
    side.user_name = _get_user_name(ctx, session)
    side.rolls = _roll(session, ctx, trait_names)
    side.options = _determine_best_choices(side.rolls)
    side.choice = RollChoice(total=0, effect=4) if not side.options else None
    # TODO Fix this so that it supports rooms that are private to the user
    message = await send_message(ctx.channel, _build_roll_message(side.user_name, side.rolls, side.options, difficulty))
    side.message_id = message.id
    await asyncio.gather(*[message.add_reaction(_get_unicode_emoji_for_choice(i)) for i in range(len(side.options))])


def _get_user_name(ctx: CommandCallContext, session: Session) -> str:
    sheet = _get_sheet(ctx, session)
    if not sheet:
        permissions = get_permissions_for_member(ctx.member)
        if permissions.is_gm:
            return "The GM"
        else:
            raise CommandException("Failed to locate Umbreal character sheet")
    else:
        return sheet.character.name


def _get_sheet(ctx: CommandCallContext, session: Session) -> Optional[UmbrealSheet]:
    try:
        character = get_channel_character(ctx, session)
    except CommandException:
        return None
    sheet = UmbrealSheet.get_for_character(session, character.id)
    return sheet


def _build_roll_message(
    name: str, results: list[DiceResult], choices: list[RollChoice], difficulty: Optional[int] = None
) -> str:
    text = (
        f"**{name}** rolls "
        + ", ".join(f"**{result.value}** ({result.name} :d{result.rating}:)" for result in results) + "."
    )
    valid_results = _get_valid_results(results)

    num_hitches = len(results) - len(valid_results)
    if num_hitches == len(results):
        text += "\n\nThis is a **botch**. Your result is **0** :d4:."
    elif num_hitches:
        text += f"\n\nThere are **{num_hitches} hitches**. "
        if difficulty is None:
            text += "The player can activate an **opportunity** for 1 :PP:."
        else:
            text += "The GM can activate **complications** (1 :PP:/complication)."

    if valid_results:
        text += (
            "\n\nYou can react with one of the following pre-determined results, or use `.testset` to specify a custom "
            "result (you can include more dice in the result by spending 1 :PP: per die):\n"
        )
        for i, choice in enumerate(choices):
            text += f"\n:{_get_emoji_name_for_choice(i)}: {choice}"

    return text


def _determine_best_choices(results: list[DiceResult]) -> list[RollChoice]:
    valid_results = _get_valid_results(results)
    choices = []
    for length in [1, 2]:
        for combo in itertools.combinations(valid_results, length):
            effects = [*(result.rating for result in valid_results if result not in combo)]
            if not effects:
                effects.append(4)  # Ensure there's always a d4 fallback
            choices.append(RollChoice(total=sum(result.value for result in combo), effect=max(effects)))
    return list(reversed(sorted(set(choices))))[:MAX_CHOICES]


def _get_valid_results(results: list[DiceResult]) -> list[DiceResult]:
    return [result for result in results if result.value != 1]


def _roll(session: Session, ctx: CommandCallContext, trait_names: Iterable[str]) -> list[DiceResult]:
    # Compile all traits which are available to the user rolling
    permissions = get_permissions_for_member(ctx.member)
    character = get_channel_character(ctx, session) if not permissions.is_gm else None
    traits_by_name_and_character: dict[str, dict[str, UmbrealTrait]] = {}
    character_traits_by_name: dict[str, UmbrealTrait] = {}
    # TODO Handle d4 complications
    for sheet in UmbrealSheet.get_all_of_guild(session, ctx.guild.id):
        valid_trait_sets = PLAYER_VALID_TRAIT_SETS if sheet.character == character else OTHER_VALID_TRAIT_SETS
        traits_by_name_and_character[sheet.character.name] = {
            trait.name: trait for trait in sheet.traits if trait.set in valid_trait_sets and trait.rating
        }
        if sheet.character == character:
            character_traits_by_name = traits_by_name_and_character[sheet.character.name]

    results = []
    for trait_string in trait_names:
        if match := DICE_ROLL_PATTERN.match(trait_string):
            num = int(match.group("num") or "1")
            rating = int(match.group("rating"))
            if rating not in VALID_DICE_RATINGS:
                raise CommandException(f"Invalid dice rating: {trait_string}")
            for _ in range(0, num):
                results.append(DiceResult(name=trait_string, value=randint(1, rating), rating=rating))
        elif match := TRAIT_ROLL_PATTERN.match(trait_string):
            character_name = match.group("character")
            trait_name = match.group("trait")
            if character_name:
                actual_character_name = fuzzy_search(character_name, traits_by_name_and_character.keys())
                if not actual_character_name:
                    raise CommandException(f"Failed to locate character: {character_name}")
                traits = traits_by_name_and_character[actual_character_name]
            else:
                traits = character_traits_by_name

            actual_trait_name = fuzzy_search(trait_name, traits.keys())
            if not actual_trait_name:
                raise CommandException(f"Failed to locate trait: {trait_name}")
            trait = traits[actual_trait_name]
            results.append(DiceResult(name=trait.name, value=randint(1, trait.rating), rating=trait.rating))
        else:
            raise CommandException(f"Invalid trait specification: {trait_string}")
    return results


def _get_emoji_name_for_choice(choice_idx: int) -> str:
    return f"regional_indicator_{chr(ord('a')+choice_idx)}"


def _get_unicode_emoji_for_choice(choice_idx: int) -> str:
    return chr(ord("🇦") + choice_idx)
