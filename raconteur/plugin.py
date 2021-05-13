from __future__ import annotations

import inspect
import logging
from functools import partial
from typing import Optional, ClassVar, TYPE_CHECKING, Union

from discord import Message, Member, TextChannel
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import Column, ForeignKey
from sqlalchemy.orm import declared_attr, declarative_mixin, relationship, RelationshipProperty

from raconteur.commands import Command, parse_message_as_command_call, COMMAND_PREFIX
from raconteur.exceptions import CommandException
from raconteur.messages import send_message
from raconteur.models.base import get_session
from raconteur.models.game import Game
from raconteur.queries import get_or_create_game

if TYPE_CHECKING:
    from raconteur.bot import RaconteurBot


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
    def guild(cls) -> RelationshipProperty:
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
                await send_message(message.channel, f"Failed to process command: {e}")
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


def has_permission_for_command(command: Command, message: Message) -> bool:
    if command.requires_player or command.requires_gm:
        with get_session() as session:
            game = get_or_create_game(
                session,
                message.guild  # type: ignore
            )
            is_gm = is_player = False
            for role in message.author.roles:
                is_gm |= role.id == game.gm_role_id
                is_player |= role.id == game.player_role_id
        if command.requires_gm and not is_gm:
            return False
        if command.requires_player and not is_player:
            return False
        return True
    else:
        return True
