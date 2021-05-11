from datetime import datetime
from typing import Iterable, Union

from discord import Intents, Client, Message, Guild, Member, TextChannel
from discord.abc import Messageable, User

from raconteur.commands import is_possible_command
from raconteur.models.base import get_session
from raconteur.plugin import Plugin
from raconteur.plugins import PLUGINS
from raconteur.queries import get_or_create_game


class RaconteurBot(Client):
    plugins: list[Plugin]

    def __init__(self) -> None:
        super().__init__(intents=_get_bot_intents())
        self.plugins = [plugin_cls(bot=self) for plugin_cls in PLUGINS]

    async def on_message(self, message: Message) -> None:
        # Ignore all DMs
        if message.guild is None:
            return

        # Ignore all messages from this bot
        if message.author == self.user:
            return

        enabled_plugins = list(self.get_enabled_plugins(
            message.guild  # type: ignore
        ))
        for plugin in enabled_plugins:
            if is_possible_command(message) and await plugin.on_command(message):
                break
        else:
            # If this was not processed as a command, broadcast it to every plugin as a regular message
            for plugin in enabled_plugins:
                await plugin.on_message(message)

    # noinspection PyUnusedLocal
    async def on_typing(self, channel: Messageable, user: Union[User, Member], when: datetime) -> None:
        # Ignore anything but a guild text channel
        if not isinstance(channel, TextChannel) or not isinstance(user, Member):
            return

        enabled_plugins = list(self.get_enabled_plugins(channel.guild))
        for plugin in enabled_plugins:
            await plugin.on_typing(channel, user)

    def get_enabled_plugins(self, guild: Guild) -> Iterable[Plugin]:
        with get_session() as session:
            game = get_or_create_game(session, guild)
            enabled_plugin_names = {game_plugin.name for game_plugin in game.plugins}
            for plugin in self.plugins:
                if plugin.__class__.__name__ in enabled_plugin_names:
                    yield plugin


def _get_bot_intents() -> Intents:
    intents = Intents.default()
    intents.members = True
    return intents
