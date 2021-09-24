import asyncio
import os.path
import pickle
import random
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Union, AsyncIterable, TYPE_CHECKING, Iterable, Sequence

from discord import Member, CategoryChannel, PermissionOverwrite, Guild, Message, TextChannel, Reaction
from fastapi import APIRouter
from humanize import naturaldelta
from sqlalchemy.orm import Session

from raconteur.commands import command, CommandCallContext
from raconteur.exceptions import CommandException
from raconteur.messages import send_message
from raconteur.models.base import get_session
from raconteur.models.game import Game
from raconteur.plugin import Plugin
from raconteur.plugins.character.communication import send_broadcast, send_status, send_message_copies
from raconteur.plugins.character.connections import toggle_lock, get_connection, toggle_hidden
from raconteur.plugins.character.models import Character, Connection, Location, CHARACTER_STATUS_MAX_LENGTH, \
    CharacterTrait, CharacterTraitType
from raconteur.plugins.character.web import character_plugin_router, characters_all, characters_yours, \
    characters_locations
from raconteur.utils import get_or_create_channel_by_name, fuzzy_search

if TYPE_CHECKING:
    from raconteur.bot import RaconteurBot

INTERCEPTION_CATEGORY = "GM"
INTERCEPTION_CHANNEL = "interception"

CACHED_MESSAGES_PATH = "plugin_characters_cached_messages.pkl"
MAX_LAST_LOCATION_MESSAGES = 3
MAX_AGE_LAST_LOCATION_MESSAGES = timedelta(days=7)


@dataclass
class CachedMessage:
    text: str
    timestamp: datetime
    author_id: Optional[int] = None
    location_id: Optional[int] = None
    message_ids: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class InterceptedMessage:
    original_message_id: int
    location_id: int
    character_id: int


class CharacterPlugin(Plugin):
    intercepted: dict[int, InterceptedMessage]

    @classmethod
    def assert_models(cls) -> None:
        assert Character
        assert Connection
        assert Location

    def __init__(self, bot: "RaconteurBot"):
        super().__init__(bot)
        self.intercepted = {}

        # Load up a cache of recent messages for various commands
        self.cached_messages = {"locations": {}, "characters": {}}
        if os.path.exists(CACHED_MESSAGES_PATH):
            with open(CACHED_MESSAGES_PATH, "rb") as f:
                self.cached_messages = pickle.load(f)

    def save_cached_message(self, cached_message: CachedMessage):
        if cached_message.author_id:
            self.cached_messages["characters"][cached_message.author_id] = cached_message
        if cached_message.location_id:
            if cached_message.location_id not in self.cached_messages["locations"]:
                self.cached_messages["locations"][cached_message.location_id] = deque(maxlen=MAX_LAST_LOCATION_MESSAGES)
            self.cached_messages["locations"][cached_message.location_id].append(cached_message)
        with open(CACHED_MESSAGES_PATH, "wb") as f:
            pickle.dump(self.cached_messages, f)


    async def on_message(self, message: Message) -> None:
        with get_session() as session:
            # Check if this is a reply to an intercepted message
            if message.reference and (intercepted := self.intercepted.get(message.reference.message_id)):
                await self.handle_interception(session, message, intercepted)
                interception_channel = await _get_or_create_interception_channel(message.guild)  # type: ignore
                interception_message: Message = await interception_channel.fetch_message(message.reference.message_id)
                await interception_message.clear_reactions()
            else:
                # Otherwise try to process it as a location message
                await self.handle_location_message(session, message)

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

    async def on_reaction_add(self, reaction: Reaction, user: Member) -> None:
        if reaction.message.id in self.intercepted and (intercepted := self.intercepted.get(reaction.message.id)):
            with get_session() as session:
                author = Character.get_by_id(session, reaction.message.guild.id, intercepted.character_id)
                if not author:
                    return
                if reaction.emoji == "✅":
                    await self.handle_interception(session, reaction.message, intercepted)
                    await reaction.message.clear_reactions()
                elif reaction.emoji == "❌":
                    author_channel: TextChannel = reaction.message.guild.get_channel(author.channel_id)
                    if author_channel:
                        await author_channel.send("Your message has been blocked by the GM.")
                    await reaction.message.clear_reactions()

    async def handle_interception(self, session: Session, message: Message, intercepted: InterceptedMessage) -> None:
        location = Location.get(session, message.guild.id, intercepted.location_id)
        author = Character.get_by_id(session, message.guild.id, intercepted.character_id)
        if not location or not author:
            return

        channels = []
        for character in location.characters:
            if character.channel_id:
                channels.append(message.guild.get_channel(character.channel_id))
        if location.channel_id:
            channels.append(message.guild.get_channel(location.channel_id))

        await self.relay_message(message, [c for c in channels if c], author=author, location=location)
        del self.intercepted[intercepted.original_message_id]

    async def handle_location_message(self, session: Session, message: Message) -> None:
        channels = []
        location = None
        if author := Character.get_for_channel(session, message.channel.id, message.author.id):
            # This is a player channel, broadcast to the other players and the GM
            if author.location:
                if author.intercept:
                    game: Game = author.game
                    interception_channel = await _get_or_create_interception_channel(
                        message.guild,  # type: ignore
                        gm_role_id=game.gm_role_id,
                        spectator_role_id=game.spectator_role_id,
                    )
                    await interception_channel.send(
                        f"The following message from **{author.name}** has been intercepted:"
                    )
                    copied_message = (await send_message_copies(
                        [interception_channel], message.content, message.attachments
                    ))[0]
                    self.intercepted[copied_message.id] = InterceptedMessage(
                        original_message_id=copied_message.id,
                        location_id=author.location.id,
                        character_id=author.id
                    )
                    await asyncio.gather(
                        copied_message.add_reaction("✅"),
                        copied_message.add_reaction("❌"),
                        message.channel.send(
                            "Your message is being held up for examination by the GM, please wait.",
                            delete_after=10 * 60,
                        ),
                        message.delete(),
                    )
                    return

                for character in author.location.characters:
                    if character.channel_id:
                        channels.append(message.guild.get_channel(character.channel_id))
                if author.location.channel_id:
                    channels.append(message.guild.get_channel(author.location.channel_id))
                location = author.location
        elif location := Location.get_for_channel(session, message.guild.id, message.channel.id):
            # This is a GM channel, broadcast to the players
            for character in location.characters:
                if character.channel_id:
                    channels.append(message.guild.get_channel(character.channel_id))
            channels.append(message.guild.get_channel(location.channel_id))
        if channels:
            await self.relay_message(message, [c for c in channels if c], author=author, location=location)
            await message.delete()

    async def relay_message(
        self,
        message: Message,
        channels: Iterable[TextChannel],
        author: Optional[Character] = None,
        location: Optional[Location] = None,
    ) -> None:
        intro = f"__**{author.name}**__\n" if author else ""
        formatted_message = f"{intro}{message.content}"
        message_ids = [
            (message_copy.channel.id, message_copy.id)
            for message_copy in await send_message_copies(channels, formatted_message, message.attachments)
        ]
        self.save_cached_message(
            CachedMessage(
                text=formatted_message,
                timestamp=message.created_at,
                author_id=author.id if author else None,
                location_id=location.id if location else None,
                message_ids=message_ids,
            )
        )

    @command(
        help_msg="Synchronizes the locations in the database with the channels on the server.",
        requires_gm=True,
    )
    async def location_sync(self, ctx: CommandCallContext) -> AsyncIterable[str]:
        yield "Syncing character channels with database"

        with get_session() as session:
            game = ctx.get_game(session)

            channel_operations = []
            locations_without_channels = []
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
                locations_without_channels.append(location)

            new_channels = await asyncio.gather(*channel_operations)
            for i, new_channel in enumerate(new_channels):
                locations_without_channels[i].channel_id = new_channel.id
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
            character = _get_channel_character(ctx, session)
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
        help_msg="Deletes the most-recently sent message. Can only be used once before sending a new message.",
        requires_player=True,
    )
    async def undo(self, ctx: CommandCallContext) -> str:
        with get_session() as session:
            character = _get_channel_character(ctx, session)
            cached_message: Optional[CachedMessage] = self.cached_messages["characters"].get(character.id)
            if cached_message:
                fetch_messages = []
                for channel_id, message_id in cached_message.message_ids:
                    channel: TextChannel = ctx.guild.get_channel(channel_id)
                    if channel:
                        fetch_message = channel.fetch_message(message_id)
                        if fetch_message:
                            fetch_messages.append(fetch_message)
                messages = [message for message in await asyncio.gather(*fetch_messages) if message]
                await asyncio.gather(*[message.delete() for message in messages])
                del self.cached_messages["characters"][character.id]
                return "Your latest message has been removed."
            else:
                return "Failed to locate a message to delete. Have you already deleted your latest message?"

    @command(
        help_msg="Moves your character to another location. If location is not specified, lists possible destinations "
                 "instead.",
        requires_player=True,
    )
    async def move(self, ctx: CommandCallContext, location: Optional[str] = None) -> Optional[str]:
        with get_session() as session:
            character = _get_channel_character(ctx, session)
            if not character.location:
                raise CommandException(f"Cannot move: your character isn't in any location yet.")
            if not location:
                # No new location specified, display a list of possible destinations
                destinations = []
                for connection in character.location.connections:
                    if connection.hidden:
                        continue
                    destination = (
                        connection.location_1 if connection.location_1 != character.location else connection.location_2
                    ).name
                    if connection.locked:
                        destination = f"*{destination}* (locked or unavailable)"
                    destinations.append(f"- {destination}")
                if destinations:
                    return f"The following destinations are available from `{character.location.name}`:\n" + "\n".join(
                        destinations
                    )
                else:
                    return f"There are no destinations available from here."

            location = location.strip()
            connection, new_location = get_connection(session, character.location, location, False)
            if not connection or not new_location:
                raise CommandException(f"Cannot move to `{location}`: no connection from `{character.location.name}`.")
            if connection.locked:
                raise CommandException(f"Cannot move to `{location}`: `{new_location.name}` is locked off.")

            # Check if enough time has passed to make the move to this location
            next_movement = character.last_movement + timedelta(seconds=connection.timer)
            now = datetime.utcnow()
            if next_movement > now:
                remaining_seconds = (next_movement - now).total_seconds()
                minutes = remaining_seconds // 60
                seconds = int(remaining_seconds % 60)
                if remaining_seconds > 59:
                    time_remaining = (
                            f"{minutes} minute" + ("s" if minutes != 1 else "")
                            + f" and {seconds} second" + ("s" if seconds != 1 else "")
                    )
                else:
                    time_remaining = f"{seconds} second" + ("s" if seconds != 1 else "")
                raise CommandException(f"Cannot move to `{location}`: {time_remaining} left before you can move there.")

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
            if not character:
                raise CommandException(f"Cannot force move: unknown character.")
            new_location = Location.get_by_name(session, ctx.guild.id, location)
            if not new_location:
                raise CommandException(f"Cannot force move **{character.name}** to `{location}`: unknown location.")
            if character.location == new_location:
                raise CommandException(
                    f"Cannot force move **{character.name}** to `{location}`: character is already in that location."
                )

            await self.move_character(ctx.guild, character, new_location)
            session.commit()
            return f"Force moved {character.name} to `{location}`"

    @command(
        help_msg="Gives a key to the named character between the two specified locations. The name must be unique for "
                 "that character.",
        requires_gm=True,
    )
    async def key_give(
            self,
            ctx: CommandCallContext,
            key_name: str,
            location_1: str,
            location_2: str,
            player: Member,
            character_name: Optional[str] = None
    ) -> str:
        location_1 = location_1.strip()
        location_2 = location_2.strip()
        key_name = key_name.strip()
        with get_session() as session:
            character = _get_character_implicit(session, player, character_name)
            if not character:
                raise CommandException(f"Cannot give key: unknown character.")
            location_1_obj = Location.get_by_name(session, ctx.guild.id, location_1)
            if not location_1_obj:
                raise CommandException(f"Cannot give key: unknown location `{location_1}`.")
            location_2_obj = Location.get_by_name(session, ctx.guild.id, location_2)
            if not location_2_obj:
                raise CommandException(f"Cannot give key: unknown location `{location_2}`.")
            for connection in location_1_obj.connections:
                if location_2_obj in (connection.location_1, connection.location_2):
                    break
            else:
                raise CommandException(f"Cannot give key: no connection between `{location_1}` and `{location_2}`.")
            if character.has_key(connection):
                raise CommandException(f"Cannot give key: **{character.name}** already has a key for this connection.")
            elif next((
                    trait for trait in character.traits
                    if trait.type == CharacterTraitType.KEY and trait.name == key_name
            ), None):
                raise CommandException(
                    f"Cannot give key: a key with the name **{key_name}** already exists for this character."
                )
            else:
                key = CharacterTrait()
                key.game = character.game
                key.character = character
                key.name = key_name
                key.type = CharacterTraitType.KEY
                key.value = str(connection.id)
                character.traits.append(key)
                session.commit()
                return (
                    f"The key **{key_name}** from `{location_1}` to `{location_2}` has been given to "
                    f"**{character.name}**."
                )

    @command(help_msg="Removes a character's key by its name.", requires_gm=True)
    async def key_remove(
            self,
            key_name: str,
            player: Member,
            character_name: Optional[str] = None
    ) -> str:
        key_name = key_name.strip()
        with get_session() as session:
            character = _get_character_implicit(session, player, character_name)
            if not character:
                raise CommandException(f"Cannot remove key: unknown character.")
            for trait in character.traits:
                if trait.type == CharacterTraitType.KEY and trait.name == key_name:
                    connection = session.get(Connection, int(trait.value))
                    if connection:
                        path = f"from `{connection.location_1.name}` to `{connection.location_2.name}`"
                    else:
                        path = "for a removed connection"
                    session.delete(trait)
                    session.commit()
                    return f"The key **{key_name}** {path} has been removed from **{character.name}**."
            else:
                raise CommandException(
                    f"Cannot remove key: character **{character.name}** does not own a key named **{key_name}**."
                )

    @command(help_msg="Locks the connection to a location.")
    async def lock(self, ctx: CommandCallContext, location: str) -> Optional[str]:
        return await toggle_lock(ctx, location, True)

    @command(help_msg="Unlocks the connection to a location.")
    async def unlock(self, ctx: CommandCallContext, location: str) -> Optional[str]:
        return await toggle_lock(ctx, location, False)

    @command(help_msg="Hides the connection to a location.", requires_gm=True)
    async def hide(self, ctx: CommandCallContext, location: str) -> Optional[str]:
        return await toggle_hidden(ctx, location, True)

    @command(help_msg="Reveals the connection to a location.", requires_gm=True)
    async def reveal(self, ctx: CommandCallContext, location: str) -> Optional[str]:
        return await toggle_hidden(ctx, location, False)

    @command(
        help_msg="Lists the items held in your inventory.",
        requires_player=True
    )
    async def inventory(self, ctx: CommandCallContext) -> Optional[str]:
        with get_session() as session:
            character = _get_channel_character(ctx, session)
            inventory_items = "\n".join(f"- **{item.name}**: {item.value}" for item in character.get_inventory())
            if inventory_items:
                return f"**{character.name}** has the following in their inventory:\n{inventory_items}"
            return f"**{character.name}** doesn't have anything in their inventory."

    @command(
        help_msg="Picks up an item with the name and description of your choice and puts it in your inventory.",
        requires_player=True
    )
    async def pickup(self, ctx: CommandCallContext, name: str, description: str) -> None:
        name = name.strip()
        description = description.strip()
        with get_session() as session:
            character = _get_channel_character(ctx, session)
            if not character.location:
                raise CommandException(f"Cannot pickup **{name}**: your character isn't in any location yet.")
            if any(item.name == name for item in character.get_inventory()):
                raise CommandException(f"Cannot pickup **{name}**: your character is already carrying this item.")
            item = CharacterTrait()
            item.game = character.game
            item.character = character
            item.type = CharacterTraitType.ITEM
            item.name = name
            item.value = description
            character.traits.append(item)
            session.commit()
            await send_broadcast(ctx.guild, character.location, f"**{character.name}** picks up **{item.name}**.")

    @command(help_msg="Drops an item held in your inventory.", requires_player=True)
    async def drop(self, ctx: CommandCallContext, name: str) -> None:
        name = name.strip()
        with get_session() as session:
            character = _get_channel_character(ctx, session)
            if not character.location:
                raise CommandException(f"Cannot drop **{name}**: your character isn't in any location yet.")
            item = next((item for item in character.get_inventory() if item.name == name), None)
            if not item:
                raise CommandException(f"Cannot drop **{name}**: your character isn't carrying this item.")
            session.delete(item)
            session.commit()
            await send_broadcast(ctx.guild, character.location, f"**{character.name}** drops **{item.name}**.")

    @command(
        help_msg="Sets a character's flag to an arbitrary value. Flags do nothing on their own, but can be used to "
                 "enable conditional descriptions of locations or store arbitrary data for other plugins to use.",
        requires_gm=True,
    )
    async def flag(self, name: str, value: str, player: Member, character_name: Optional[str] = None) -> str:
        name = name.strip() if name is not None else None
        value = value.strip() if value is not None else None
        with get_session() as session:
            character = _get_character_implicit(session, player, character_name)
            if not character:
                raise CommandException(f"Cannot set flag `{name}`: unknown character.")
            if not re.match(r"^[a-z_]+$", name):
                raise CommandException(
                    f"Cannot set flag `{name}`: invalid name, must consist only of lowercase letters and underscores."
                )
            for trait in character.traits:
                if trait.type == CharacterTraitType.FLAG and trait.name == name:
                    break
            else:
                trait = CharacterTrait()
                trait.game = character.game
                trait.name = name
                trait.type = CharacterTraitType.FLAG
                character.traits.append(trait)
            trait.value = value
            session.commit()
            return f"Successfully set flag `{name}` to \"{value}\"."

    # TODO Add radio commands

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
                # Special case for the d100
                if num_sides == 100:
                    rolls.append((random.randint(0, num_sides - 1), num_sides))
                else:
                    rolls.append((random.randint(1, num_sides), num_sides))
        roll_results = " + ".join(
            (str(roll).zfill(2) if num_sides == 100 else str(roll)) + f" [d{num_sides}]" for roll, num_sides in rolls
        )
        if len(rolls) == 1:
            roll_message = f"rolled {roll_results}"
        else:
            total = sum(roll for roll, num_sides in rolls)
            roll_message = f"rolled **{total}** = {roll_results}"
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
                return f"**{ctx.message.author.display_name}** " + roll_message

    @command(help_msg="Toggles a character's messages for interception by the GM.", requires_gm=True)
    async def intercept(self, ctx: CommandCallContext, player: Member, name: Optional[str] = None) -> str:
        with get_session() as session:
            character = _get_character_implicit(session, player, name)
            character.intercept = not character.intercept
            session.commit()
            game = ctx.get_game(session)
            channel = await _get_or_create_interception_channel(
                ctx.guild, gm_role_id=game.gm_role_id, spectator_role_id=game.spectator_role_id
            )
            if character.intercept:
                return (
                    f"**{character.name}**'s messages are now being intercepted in {channel.mention}:\n"
                    f"- React to a message with :white_check_mark: to allow it"
                    f"- React to a message with :x: to block it"
                    f"- Reply to a message to replace the original text with the new text in your reply."
                )
            else:
                return f"**{character.name}**'s messages are no longer being intercepted."

    async def move_character(self, guild: Guild, character: Character, new_location: Location) -> None:
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

        # Replay the last few messages in the channel from the past week
        channel: TextChannel = guild.get_channel(character.channel_id) if character.channel_id else None
        last_messages: Sequence[CachedMessage] = self.cached_messages["locations"].get(new_location.id, [])
        now = datetime.now()
        min_timestamp = now - MAX_AGE_LAST_LOCATION_MESSAGES
        texts = [
            cached_message.text for cached_message in last_messages if cached_message.timestamp > min_timestamp
        ]
        if texts and channel:
            await send_message(
                channel,
                f"_*Recent activity (last message sent {naturaldelta(now - last_messages[-1].timestamp)} ago):*_\n\n"
                + "\n\n".join(texts)
            )

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


def _get_channel_character(ctx: CommandCallContext, session: Session) -> Character:
    character = Character.get_for_channel(session, ctx.channel.id, ctx.member.id)
    if not character:
        raise CommandException(f"Cannot process command: none of your characters are associated with this channel.")
    return character


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
    characters_by_name = {
        character.name: character for character in Character.get_all_of_member(session, member.guild.id, member.id)
    }
    exact_name = fuzzy_search(name, characters_by_name.keys())
    if exact_name is not None:
        return characters_by_name[exact_name]
    return None


async def _get_or_create_interception_channel(
        guild: Guild,
        gm_role_id: Optional[int] = None,
        spectator_role_id: Optional[int] = None,
) -> TextChannel:
    """Gets the channel which holds intercepted messages, or creates it if missing.

    The GM role ID and spectator role ID should be specified if the channel is being created, but as a convenience, they
    can be left empty if it is certain the channel exists (for example when handling reacts to messages inside it).
    """
    overwrites = {
        guild.default_role: PermissionOverwrite(read_messages=False),
        guild.me: PermissionOverwrite(read_messages=True, send_messages=True),
        guild.get_role(gm_role_id): PermissionOverwrite(read_messages=True, send_messages=True),
        guild.get_role(spectator_role_id): PermissionOverwrite(
            read_messages=True, send_messages=False
        ),
    } if gm_role_id and spectator_role_id else None
    return await get_or_create_channel_by_name(
        guild,
        INTERCEPTION_CHANNEL,
        INTERCEPTION_CATEGORY,
        create_channel_permissions=overwrites,
        create_category_permissions=overwrites,
    )
