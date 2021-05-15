from typing import Optional, Any

from discord import Guild, TextChannel, PermissionOverwrite, CategoryChannel


async def get_or_create_channel_by_name(
        guild: Guild,
        channel_name: str,
        category_name: Optional[str] = None,
        create_channel_permissions: Optional[dict[Any, PermissionOverwrite]] = None,
        create_category_permissions: Optional[dict[Any, PermissionOverwrite]] = None,
) -> TextChannel:
    channel = get_channel_by_name(guild, channel_name, category_name)
    if channel:
        return channel
    category = None
    if category_name:
        category = get_category_by_name(guild, category_name)
        if not category:
            category = await guild.create_category(category_name, overwrites=create_category_permissions)
    return await guild.create_text_channel(channel_name, category=category, overwrites=create_channel_permissions)


def get_channel_by_name(
        guild: Guild,
        channel_name: str,
        category_name: Optional[str] = None,
) -> Optional[TextChannel]:
    if category_name:
        category = get_category_by_name(guild, category_name)
        if not category:
            return None
        channels = category.channels
    else:
        channels = guild.channels
    for channel in channels:
        if isinstance(channel, TextChannel) and channel.name == channel_name:
            return channel
    return None


def get_category_by_name(guild: Guild, category_name: str) -> Optional[CategoryChannel]:
    for category in guild.categories:
        if category.name == category_name:
            return category
    return None
