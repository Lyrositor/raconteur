import asyncio
from datetime import datetime
from io import BytesIO
from typing import Iterable, Optional

from discord import Guild, Embed, TextChannel, Message, File, Attachment
from jinja2 import Environment, Template

from raconteur.messages import send_message
from raconteur.plugins.character.models import Location, Character, CharacterTraitType


async def relay_message(message: Message, channels: Iterable[TextChannel], author: Optional[Character] = None) -> None:
    intro = f"__**{author.name}**__\n" if author else ""
    formatted_message = f"{intro}{message.content}"
    await send_message_copies(channels, formatted_message, message.attachments)


async def send_message_copies(
        channels: Iterable[TextChannel], text: str, attachments: Optional[list[Attachment]] = None
) -> list[Message]:
    attachments_data = await asyncio.gather(*[attachment.read() for attachment in attachments]) if attachments else None

    relays = []
    for channel in channels:
        files = None
        if attachments and attachments_data:
            # The files need to be recreated because the .close() method is called on each of them once they are sent,
            # preventing them from being reused
            files = [
                File(BytesIO(attachment_data), filename=attachments[i].filename, spoiler=attachments[i].is_spoiler())
                for i, attachment_data in enumerate(attachments_data)
            ]
        relays.append(send_message(channel, text, files=files))
    copied_messages = await asyncio.gather(*relays)
    return copied_messages  # type: ignore


async def send_broadcast(guild: Guild, location: Location, text: str) -> None:
    channels = []
    for character in location.characters:
        if channel := guild.get_channel(character.channel_id):
            channels.append(channel)
    if channel := guild.get_channel(location.channel_id):
        channels.append(channel)
    await asyncio.gather(*[send_message(channel, text) for channel in channels])


async def send_status(guild: Guild, character: Character) -> None:
    channel: TextChannel = guild.get_channel(character.channel_id)
    if not channel:
        return
    now = datetime.utcnow()
    if character.location:
        last_week = last_day = last_hour = 0
        async for message in channel.history(limit=50):
            seconds = (now - message.created_at).total_seconds()
            if seconds <= 3600:
                last_hour += 1
            if seconds <= 3600 * 24:
                last_day += 1
            if seconds <= 3600 * 24 * 7:
                last_week += 1
        if last_hour > 1:
            business = f"Looks like it's been {_get_business_qualifier(last_hour, 50)} here very recently."
        elif last_day:
            business = f"Looks like it's been {_get_business_qualifier(last_day, 50)} here over the past day."
        elif last_week:
            business = f"Looks like it's been {_get_business_qualifier(last_week, 50)} here over the past week."
        else:
            business = f"Looks it's been very quiet here recently."

        # TODO Template the description with Jinja2
        environment = Environment(autoescape=False)
        template: Template = environment.from_string(character.location.description)
        description = template.render(
            character_name=character.name,
            flag={trait.name: trait.value for trait in character.traits if trait.type == CharacterTraitType.FLAG},
        )
        embed = Embed(title=character.location.name, description=description)
        for character in character.location.characters:
            embed.add_field(name=character.name, value=character.status or "(Unknown status)", inline=True)
        embed.set_footer(text=business)
    else:
        embed = Embed(title=f"???", description="(Unknown location)")
    await channel.send(embed=embed)


def _get_business_qualifier(quantity: int, max_quantity: int) -> str:
    if quantity / max_quantity < 0.1:
        return "somewhat active"
    elif quantity / max_quantity < 0.5:
        return "fairly busy"
    else:
        return "extremely lively"
