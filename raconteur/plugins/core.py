import asyncio
from typing import AsyncIterable, Union

from discord import Colour, Role

from raconteur.commands import command, CommandCallContext
from raconteur.exceptions import CommandException
from raconteur.models.base import get_session
from raconteur.models.game import GamePlugin
from raconteur.plugin import Plugin, has_permission_for_command


class CorePlugin(Plugin):
    @command(help_msg="Displays a list of commands you can run.")
    async def help(self, ctx: CommandCallContext) -> str:
        valid_commands = []
        for plugin in self.bot.get_enabled_plugins(ctx.guild):
            for plugin_command in plugin.commands.values():
                if has_permission_for_command(plugin_command, ctx.message):
                    valid_commands.append(str(plugin_command))
        return "\n".join(valid_commands)

    @command(help_msg="Sets up the server for a new game.")
    async def init(self, ctx: CommandCallContext) -> AsyncIterable[str]:

        with get_session() as session:
            game = ctx.get_game(session)

            if game.gm_role_id and game.player_role_id and game.spectator_role_id:
                yield "Game session is already initialized"
                return
            else:
                yield "Initializing game session"

            role_operations = []
            if not game.gm_role_id:
                role_operations.append(
                    ("gm_role_id", (ctx.message.guild.create_role(name="Game Master", colour=Colour.dark_blue())))
                )
            if not game.player_role_id:
                role_operations.append(
                    ("player_role_id", ctx.message.guild.create_role(name="Player", colour=Colour.dark_red()))
                )
            if not game.spectator_role_id:
                role_operations.append(
                    ("spectator_role_id", ctx.message.guild.create_role(name="Spectator", colour=Colour.orange()))
                )
            if role_operations:
                yield "Setting up roles for game session"
                roles: tuple[Role] = tuple(  # type: ignore
                    await asyncio.gather(*(op for attribute_name, op in role_operations))
                )
                for i, (attribute_name, op) in enumerate(role_operations):
                    setattr(game, attribute_name, roles[i].id)

            session.commit()

        yield "Initialization complete"

    @command(help_msg="Enables a plugin for this server.", requires_gm=True)
    async def plugin_enable(self, ctx: CommandCallContext, name: str) -> str:
        for plugin in self.bot.plugins:
            if plugin.__class__.__name__ == name:
                with get_session() as session:
                    game = ctx.get_game(session)
                    game_plugin = game.get_plugin(name)
                    if game_plugin:
                        return f"Plugin **{name}** is already enabled"
                    else:
                        game.plugins.append(GamePlugin(name=name))
                        session.commit()
                        return f"Plugin **{name}** has been enabled"
        raise CommandException(f'Unknown plugin "{name}"')

    @command(help_msg="Disables a plugin for this server.", requires_gm=True)
    async def plugin_disable(self, ctx: CommandCallContext, name: str) -> str:
        if name == self.__class__.__name__:
            return f"Cannot disable **{self.__class__.__name__}**"
        for plugin in self.bot.plugins:
            if plugin.__class__.__name__ == name:
                with get_session() as session:
                    game = ctx.get_game(session)
                    game_plugin = game.get_plugin(name)
                    if not game_plugin:
                        return f"Plugin **{name}** is already disabled"
                    else:
                        game.plugins.remove(game_plugin)
                        session.commit()
                        return f"Plugin **{name}** has been disabled"
        raise CommandException(f"Unknown plugin **{name}**")

    @command(help_msg="Sets a plugin setting.", requires_gm=True)
    async def setting(self, ctx: CommandCallContext, plugin: str, name: str, value: str) -> str:
        with get_session() as session:
            parsed_value = convert_setting_value(value)
            self.set_setting(ctx.guild, session, name, parsed_value, plugin)
            return f"Successfully set `{plugin}.{name}` to `{parsed_value}`"


def convert_setting_value(value: str) -> Union[None, bool, int, float, str]:
    cleaned_value = value.strip().lower()
    if cleaned_value == "true":
        return True
    elif cleaned_value == "false":
        return False
    elif cleaned_value == "none":
        return None

    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass

    return value

