import asyncio
import random
import re
from datetime import datetime, timedelta
from typing import Optional, Union, AsyncIterable

from discord import Member, CategoryChannel, PermissionOverwrite, Guild, Message, TextChannel
from fastapi import APIRouter
from sqlalchemy.orm import Session

from raconteur.commands import command, CommandCallContext
from raconteur.exceptions import CommandException
from raconteur.models.base import get_session
from raconteur.plugin import Plugin
from raconteur.plugins.character.communication import send_broadcast, send_status, relay_message
from raconteur.plugins.character.models import Character, Connection, Location, CHARACTER_STATUS_MAX_LENGTH
from raconteur.plugins.character.web import character_plugin_router, characters_all, characters_yours, \
    characters_locations


class CharacterPlugin(Plugin):
    @classmethod
    def assert_models(cls) -> None:
        assert Character
        assert Connection
        assert Location

    async def on_message(self, message: Message) -> None:
        with get_session() as session:
            channels = []
            if author := Character.get_for_channel(session, message.channel.id, message.author.id):
                # This is a player channel, broadcast to the other players and the GM
                if author.location:
                    for character in author.location.characters:
                        if character.channel_id:
                            channels.append(message.guild.get_channel(character.channel_id))
                    if author.location.channel_id:
                        channels.append(message.guild.get_channel(author.location.channel_id))
            elif location := Location.get_for_channel(session, message.guild.id, message.channel.id):
                # This is a GM channel, broadcast to the players
                for character in location.characters:
                    if character.channel_id:
                        channels.append(message.guild.get_channel(character.channel_id))
            if channels:
                await relay_message(message, [c for c in channels if c], author=author)
                await message.delete()

    async def on_typing(self, channel: TextChannel, member: Member) -> None:
        with get_session() as session:
            if author := Character.get_for_channel(session, channel.id, member.id):
                typings = []
                for character in author.location.characters:
                    if character != author and (relay_channel := channel.guild.get_channel(character.channel_id)):
                        typings.append(relay_channel.trigger_typing())
                await asyncio.gather(*typings)
            elif location := Location.get_for_channel(session, channel.guild.id, channel.id):
                typings = []
                for character in location.characters:
                    if relay_channel := channel.guild.get_channel(character.channel_id):
                        typings.append(relay_channel.trigger_typing())
                await asyncio.gather(*typings)

    @command(
        help_msg="Synchronizes the locations in the database with the channels on the server.",
        requires_gm=True,
    )
    async def location_sync(self, ctx: CommandCallContext) -> AsyncIterable[str]:
        yield "Syncing character channels with database"

        with get_session() as session:
            game = ctx.get_game(session)

            channel_operations = []
            locations = Location.get_all(session, ctx.guild.id)
            for location in locations:
                if ctx.guild.get_channel(location.channel_id):
                    continue
                category_channel = next(
                    (c for c in ctx.guild.channels if isinstance(c, CategoryChannel) and c.name == location.category),
                    None
                )
                overwrites = {
                    ctx.guild.default_role: PermissionOverwrite(read_messages=False),
                    ctx.guild.me: PermissionOverwrite(read_messages=True, send_messages=True),
                    ctx.guild.get_role(game.gm_role_id): PermissionOverwrite(read_messages=True, send_messages=True),
                    ctx.guild.get_role(game.spectator_role_id): PermissionOverwrite(
                        read_messages=True, send_messages=False
                    ),
                }
                if not category_channel:
                    category_channel = await ctx.guild.create_category(location.category, overwrites=overwrites)
                channel_operations.append(
                    ctx.guild.create_text_channel(location.name, overwrites=overwrites, category=category_channel)
                )

            new_channels = await asyncio.gather(*channel_operations)
            for i, new_channel in enumerate(new_channels):
                location = locations[i]
                location.channel_id = new_channel.id
            session.commit()
            if new_channels:
                yield "Created the following channels:" + "".join(f"\n- <#{channel.id}>" for channel in new_channels)

        yield "Sync complete"

    @command(
        help_msg="Sets the Discord channel bound to a specific character.",
        requires_gm=True,
    )
    async def char_channel_set(self, ctx: CommandCallContext, player: Member, name: Optional[str] = None) -> str:
        with get_session() as session:
            character = _get_character_implicit(session, player, name)
            if character.channel_id == ctx.channel.id:
                return f"This channel is already bound to **{character.name}**"
            character.channel_id = ctx.channel.id
            session.commit()
            return f"This channel has been bound to **{character.name}**"

    @command(
        help_msg="Unsets the Discord channel bound to a specific character.",
        requires_gm=True,
    )
    async def char_channel_unset(self, player: Member, name: Optional[str] = None) -> str:
        with get_session() as session:
            character = _get_character_implicit(session, player, name)
            if character.channel_id is None:
                return f"**{character.name}** doesn't have a channel bound to them"
            character.channel_id = None
            session.commit()
            return f"**{character.name}** has been unbound from a channel"

    @command(
        help_msg=f"Displays the current status of the room if no value is provided. Otherwise, sets your character's "
                 f"status message to that value (maximum {CHARACTER_STATUS_MAX_LENGTH} characters).",
        requires_player=True,
    )
    async def status(self, ctx: CommandCallContext, status: Optional[str] = None) -> Optional[str]:
        with get_session() as session:
            character = Character.get_for_channel(session, ctx.channel.id, ctx.member.id)
            if not character:
                return f"Cannot process command: none of your characters are associated with this channel."
            if status is None:
                await send_status(ctx.guild, character)
            else:
                status = status.strip()
                if len(status) > CHARACTER_STATUS_MAX_LENGTH:
                    raise CommandException(f"Status is too long (maximum {CHARACTER_STATUS_MAX_LENGTH} characters)")
                character.status = status
                session.commit()
            return None

    @command(
        help_msg="Moves your character to another location.",
        requires_player=True,
    )
    async def move(self, ctx: CommandCallContext, location: str) -> Optional[str]:
        location = location.strip()
        with get_session() as session:
            character = Character.get_for_channel(session, ctx.channel.id, ctx.member.id)
            if not character:
                return f"Cannot move to `{location}`: none of your characters are associated with this channel."
            if not character.location:
                return f"Cannot move to `{location}`: your character isn't in any location yet."
            new_location = Location.get_by_name(session, ctx.guild.id, location)
            for connection in character.location.connections:
                if not connection.hidden and new_location and new_location in (
                        connection.location_1, connection.location_2
                ):
                    break
            else:
                return f"Cannot move to `{location}`: no connection from `{character.location.name}`."
            if connection.locked:
                return f"Cannot move to `{location}`: `{new_location.name}` is locked off."

            # Check if enough time has passed to make the move to this location
            next_movement = character.last_movement + timedelta(minutes=connection.timer)
            now = datetime.utcnow()
            if next_movement > now:
                remaining_seconds = (next_movement - now).total_seconds()
                minutes = remaining_seconds // 60
                seconds = remaining_seconds % 60
                if remaining_seconds > 59:
                    time_remaining = (
                            f"{minutes} minute" + ("s" if minutes != 1 else "")
                            + f" and {seconds} second" + ("s" if seconds != 1 else "")
                    )
                else:
                    time_remaining = f"{seconds} second" + ("s" if seconds != 1 else "")
                return f"Cannot move to `{location}: {time_remaining} left before you can move there." \
                       f""

            await self.move_character(ctx.guild, character, new_location)
            session.commit()
            return None

    @command(
        help_msg="Moves a player's character to another character, even if there are no connections to it.",
        requires_gm=True,
    )
    async def move_force(
            self, ctx: CommandCallContext, location: str, player: Member, name: Optional[str] = None
    ) -> str:
        location = location.strip()
        with get_session() as session:
            character = _get_character_implicit(session, player, name)
            new_location = Location.get_by_name(session, ctx.guild.id, location)
            if not new_location:
                return f"Cannot force move **{character.name}** to `{location}`: unknown location."
            if character.location == new_location:
                return f"Cannot force move **{character.name}** to `{location}`: character is already in that location."

            await self.move_character(ctx.guild, character, new_location)
            session.commit()
            return f"Force moved {character.name} to `{location}`"

    @command(help_msg="Rolls a d100.")
    async def d100(self, ctx: CommandCallContext) -> Optional[str]:
        return await self.roll(ctx, "1d100")

    @command(help_msg="Rolls a d10.")
    async def d10(self, ctx: CommandCallContext) -> Optional[str]:
        return await self.roll(ctx, "1d10")

    @command(help_msg="Rolls a set of standard polyhedral dice (d4, d6, d8, d10, d12, d20, d100). Example: 1d6 3d8")
    async def roll(self, ctx: CommandCallContext, dice: str) -> Optional[str]:
        elements = re.split(r"\s+", dice.strip())
        rolls = []
        for element in elements:
            if not (match := re.match(r"^(\d+)d(\d+)$", element)):
                raise CommandException("Invalid roll request")
            num_dice, num_sides = int(match.group(1)), int(match.group(2))
            for _ in range(num_dice):
                rolls.append((random.randint(1, num_sides), num_sides))
        total = sum(roll for roll, num_sides in rolls)
        roll_message = f"rolled **{total}** = " + " + ".join(f"{roll} [d{num_sides}]" for roll, num_sides in rolls)
        with get_session() as session:
            if location := Location.get_for_channel(session, ctx.guild.id, ctx.channel.id):
                await send_broadcast(ctx.guild, location, f"**The GM** " + roll_message)
                return None
            elif (
                    (character := Character.get_for_channel(session, ctx.channel.id, ctx.member.id))
                    and character.location
            ):
                await send_broadcast(ctx.guild, character.location, f"**{character.name}** " + roll_message)
                return None
            else:
                return f"**{ctx.message.author.display_name}**" + roll_message

    @staticmethod
    async def move_character(guild: Guild, character: Character, new_location: Location) -> None:
        character.last_movement = datetime.utcnow()
        if character.location:
            await send_broadcast(
                guild, character.location, f"**{character.name}** moves to `{new_location.name}`"
            )
        await send_broadcast(
            guild,
            new_location,
            f"**{character.name}** moves in from `{character.location.name}`"
            if character.location else f"**{character.name}** appears"
        )
        character.location = new_location
        await send_status(guild, character)

    @classmethod
    def get_web_router(cls) -> Optional[APIRouter]:
        return character_plugin_router

    @classmethod
    def get_web_menu(cls) -> dict[str, Union[str, dict[str, str]]]:
        return {
            "Characters": characters_all.__name__,
            "Game Master": {
                "Locations": characters_locations.__name__,
            },
            "Your Data": {
                "Characters": characters_yours.__name__,
            },
        }


def _get_character_implicit(session: Session, player: Member, name: Optional[str] = None) -> Character:
    if name:
        character = _get_character_fuzzy(session, player, name.strip())
        if not character:
            raise CommandException(f"Failed to locate character with name **{name}**")
        return character
    else:
        characters = Character.get_all_of_member(session, player.guild.id, player.id)
        if len(characters) > 1:
            raise CommandException("Player has multiple characters, please specify one of the following: " + ", ".join(
                character.name for character in characters
            ))
        elif not characters:
            raise CommandException(f"Player has no associated characters")
        return characters[0]


def _get_character_fuzzy(session: Session, member: Member, name: str) -> Optional[Character]:
    # TODO Actually make this fuzzy
    return Character.get_by_name_and_member(session, member.guild.id, member.id, name)
