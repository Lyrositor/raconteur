import asyncio
from typing import Optional

from sqlalchemy.orm import Session

from raconteur.commands import CommandCallContext
from raconteur.exceptions import CommandException
from raconteur.models.base import get_session
from raconteur.plugin import get_permissions_for_member
from raconteur.plugins.character.communication import send_broadcast
from raconteur.plugins.character.models import Connection, Location, Character


async def toggle_lock(ctx: CommandCallContext, location_name: str, lock: bool) -> None:
    change = "lock" if lock else "unlock"
    permissions = get_permissions_for_member(ctx.member)
    with get_session() as session:
        character = Character.get_for_channel(session, ctx.channel.id, ctx.member.id)
        if not character:
            raise CommandException(
                f"Cannot {change} `{location_name}`: none of your characters are associated with this channel."
            )
        if not character.location:
            raise CommandException(
                f"Cannot {change} `{location_name}`: your character isn't in any location yet."
            )
        connection, other_location = get_connection(session, character.location, location_name, False)
        if not connection:
            raise CommandException(
                f"Cannot {change} `{location_name}`: no connection to `{location_name}` from here."
            )
        if permissions.is_gm or permissions.is_player and character.has_key(connection):
            if connection.locked is lock:
                raise CommandException(
                    f"Cannot {change} `{location_name}`: connection is already {change}ed."
                )
            else:
                connection.locked = lock
                session.commit()
                await asyncio.gather(
                    send_broadcast(
                        ctx.guild,
                        connection.location_1,
                        f"The connection to `{connection.location_2.name}` has been {change}ed."
                    ),
                    send_broadcast(
                        ctx.guild,
                        connection.location_2,
                        f"The connection to `{connection.location_1.name}` has been {change}ed."
                    ),
                )
                return None
        else:
            raise CommandException(
                f"Cannot {change} `{location_name}`: your character does not own the right key."
            )


async def toggle_hidden(ctx: CommandCallContext, location_name: str, hide: bool) -> None:
    change = "hide" if hide else "reveal"
    change_result = "hidden" if hide else "revealed"
    with get_session() as session:
        location = Location.get_for_channel(session, ctx.guild.id, ctx.channel.id)
        if not location:
            raise CommandException(
                f"Cannot {change} `{location_name}`: no location bound to this channel."
            )
        connection, other_location = get_connection(session, location, location_name, True)
        if not connection:
            raise CommandException(
                f"Cannot {change} `{location_name}`: no connection to `{location_name}` from here."
            )
        if connection.hidden is hide:
            raise CommandException(
                f"Cannot {change} `{location_name}`: connection is already {change_result}."
            )
        else:
            connection.hidden = hide
            session.commit()
            await asyncio.gather(
                send_broadcast(
                    ctx.guild,
                    connection.location_1,
                    f"The connection to `{connection.location_2.name}` has been {change_result}."
                ),
                send_broadcast(
                    ctx.guild,
                    connection.location_2,
                    f"The connection to `{connection.location_1.name}` has been {change_result}."
                ),
            )
            return None


def get_connection(
        session: Session, location: Location, new_location_name: str, include_hidden: bool
) -> tuple[Optional[Connection], Optional[Location]]:
    new_location = Location.get_by_name(session, location.game_guild_id, new_location_name.strip())
    if not new_location:
        return None, None
    for connection in location.connections:
        if (include_hidden or not connection.hidden) and new_location and new_location in (
                connection.location_1, connection.location_2
        ):
            return connection, new_location
    return None, None
