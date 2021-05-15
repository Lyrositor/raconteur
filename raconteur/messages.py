from typing import Optional

from discord import TextChannel, File, Message

MESSAGE_CHARS_LIMIT = 2000


async def send_message(channel: TextChannel, text: str, files: Optional[list[File]] = None) -> Message:
    lines = text.split("\n")
    messages = [""]
    for line in lines:
        if len(messages[-1] + line) > MESSAGE_CHARS_LIMIT:
            messages.append("")
            if len(line) > MESSAGE_CHARS_LIMIT:
                messages[-1] += line[:MESSAGE_CHARS_LIMIT]
                messages.append("")
                line = line[MESSAGE_CHARS_LIMIT:]
        messages[-1] += line + "\n"
    last_idx = len(messages) - 1
    last_message = None
    for i, message in enumerate(messages):
        last_message = await channel.send(message.strip(), files=(files if i == last_idx else None))
    assert last_message
    return last_message
