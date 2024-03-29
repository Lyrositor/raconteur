from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from functools import partial
from typing import Optional, ClassVar, TYPE_CHECKING, Union, Any

from discord import Message, Member, TextChannel, Reaction, Guild
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import Column, ForeignKey
from sqlalchemy.orm import declared_attr, declarative_mixin, relationship, RelationshipProperty, Session

from raconteur.commands import Command, parse_message_as_command_call, COMMAND_PREFIX, CommandCallContext
from raconteur.exceptions import CommandException
from raconteur.messages import send_message
from raconteur.models.base import get_session
from raconteur.models.game import Game
from raconteur.queries import get_or_create_game

if TYPE_CHECKING:
    from raconteur.bot import RaconteurBot


@dataclass
class Permissions:
    is_gm: bool = False
    is_player: bool = False


@declarative_mixin
class PluginModelMixin:
    __plugin__: ClassVar[str]
    __table__: ClassVar[str]

    # noinspection PyMethodParameters
    @declared_attr
    def __tablename__(cls) -> str:
        return f"{cls.__plugin__}__{cls.__plugin_table_name__}"  # type: ignore

    # noinspection PyMethodParameters
    @declared_attr
    def game_guild_id(cls) -> Column:
        return Column("game_guild_id", ForeignKey(Game.guild_id), nullable=False)

    # noinspection PyMethodParameters
    @declared_attr
    def game(cls) -> RelationshipProperty:
        return relationship(Game)


class PluginSettings(BaseModel):
    pass


class Plugin:
    bot: RaconteurBot
    commands: dict[str, Command]

    def __init__(self, bot: RaconteurBot):
        self.bot = bot
        self.commands = self.get_commands()

    async def on_command(self, message: Message) -> bool:
        command_call = parse_message_as_command_call(self.commands, message)
        if command_call:
            full_command_name = COMMAND_PREFIX + command_call.command.name
            try:
                if not has_permission_for_command(command_call.command, message):
                    raise CommandException(f"Insufficient permissions to use command `{full_command_name}`")
                async for result in command_call.invoke(message):
                    if result.text:
                        await send_message(message.channel, result.text)
            except CommandException as e:
                await message.add_reaction("🚫")
                await send_message(message.channel, str(e))
            except Exception as e:
                await message.add_reaction("🚫")
                await send_message(message.channel, f"Failed to process command: Unknown error")
                logging.exception(e)
            else:
                await message.delete()
                logging.info(
                    f"Successfully processed command {full_command_name} from "
                    f"{message.author}"
                )
            return True
        return False

    async def on_message(self, message: Message) -> None:
        pass

    async def on_typing(self, channel: TextChannel, member: Member) -> None:
        pass

    async def on_reaction_add(self, reaction: Reaction, user: Member) -> None:
        pass

    def get_setting(self, session: Session, guild: Guild, name: str) -> Optional[Any]:
        return get_setting(self.__class__.__name__, session, guild, name)

    def set_setting(self, guild: Guild, session: Session, name: str, value: Any, plugin: Optional[str] = None) -> None:
        plugin = plugin or self.__class__.__name__
        game = session.get(Game, guild.id)
        if not game:
            raise CommandException("Game is not initialized")
        game_plugin = game.get_plugin(plugin)
        if not game_plugin:
            raise CommandException(f"Plugin {plugin} is not enabled")
        game_plugin.settings[name] = value
        session.commit()

    def get_commands(self) -> dict[str, Command]:
        commands: dict[str, Command] = {}
        for item_name in dir(self):
            item = getattr(self, item_name)
            if inspect.isasyncgenfunction(item) or inspect.iscoroutinefunction(item):
                if hasattr(item, "command_metadata"):
                    cmd: Command = item.command_metadata
                    cmd.callback = partial(cmd.callback, self)  # type: ignore
                    commands[cmd.name] = cmd
        return commands

    @classmethod
    def assert_models(cls) -> None:
        pass

    @classmethod
    def get_web_router(cls) -> Optional[APIRouter]:
        return None

    @classmethod
    def get_web_menu_for_game(cls, game: Optional[Game]) -> dict[str, Union[str, dict[str, str]]]:
        if game:
            for game_plugin in game.plugins:
                if game_plugin.name == cls.__name__:
                    return cls.get_web_menu()
        return {}

    @classmethod
    def get_web_menu(cls) -> dict[str, Union[str, dict[str, str]]]:
        return {}


def get_setting(plugin: str, session: Session, guild: Guild, name: str) -> Optional[Any]:
    plugin = plugin
    game = session.get(Game, guild.id)
    if not game:
        raise CommandException("Game is not initialized")
    game_plugin = game.get_plugin(plugin)
    if not game_plugin:
        raise CommandException(f"Plugin {plugin} is not enabled")
    return game_plugin.settings.get(name)


def has_permission_for_command(command: Command, message: Message) -> bool:
    if command.requires_player or command.requires_gm:
        permissions = get_permissions_for_member(message.author)
        if command.requires_gm and not permissions.is_gm:
            return False
        if command.requires_player and not permissions.is_player:
            return False
        return True
    else:
        return True


def get_permissions_for_member(member: Member) -> Permissions:
    permissions = Permissions()
    with get_session() as session:
        game = get_or_create_game(
            session,
            member.guild,
        )
        for role in member.roles:
            permissions.is_gm |= role.id == game.gm_role_id
            permissions.is_player |= role.id == game.player_role_id
    return permissions
