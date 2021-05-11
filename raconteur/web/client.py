from typing import Optional

from discord import Client

from raconteur.config import config

_cached_client: Optional[Client] = None


async def get_client() -> Client:
    global _cached_client

    if _cached_client:
        return _cached_client

    _cached_client = Client()
    await _cached_client.login(config.bot_token)
    return _cached_client
