import inspect
import re
from dataclasses import dataclass
from typing import Optional, Union, Type, Callable, Any, AsyncIterable, Coroutine

from discord import Message, Guild, Role, TextChannel, Member
from sqlalchemy.orm import Session

from raconteur.exceptions import CommandException, CommandParamValueException, \
    CommandParamUserNotFoundException, CommandParamRoleNotFoundException, CommandParamChannelNotFoundException, \
    CommandParamMissingException
from raconteur.models.game import Game
from raconteur.queries import get_or_create_game

COMMAND_PREFIX = "."

ParamType = Union[
    Type[str],
    Type[bool],
    Type[int],
    Type[Member],
    Type[TextChannel],
    Type[Role],
]

ParamValueType = Union[
    str,
    bool,
    int,
    Member,
    TextChannel,
    Role,
]

USER_MENTION_PATTERN = re.compile(r"^<@!?([0-9]+)>$")
ROLE_MENTION_PATTERN = re.compile(r"^<@&([0-9]+)>$")
CHANNEL_MENTION_PATTERN = re.compile(r"^<#([0-9]+)>$")

CONTEXT_ARG = "ctx"


@dataclass(frozen=True)
class CommandCallResponse:
    text: Optional[str] = None


@dataclass(frozen=True)
class CommandParam:
    name: str
    type: ParamType
    required: bool = True
    collect: bool = False

    def parse(
            self, guild: Guild, param_value: Union[str, list[str]]
    ) -> Union[ParamValueType, tuple[ParamValueType, ...]]:
        if isinstance(param_value, list):
            return tuple(self.parse(guild, pv) for pv in param_value)

        param_value_clean = param_value.strip().lower()
        if self.type == str:
            return param_value
        elif self.type == bool:
            if param_value_clean in ("true", "1", "on", "yes"):
                return True
            elif param_value_clean in ("false", "0", "off", "no"):
                return False
            raise CommandParamValueException(self.name, param_value)
        elif self.type == int:
            try:
                return int(param_value)
            except ValueError:
                raise CommandParamValueException(self.name, param_value)
        elif self.type == Member:
            user = None
            if match := USER_MENTION_PATTERN.match(param_value.strip()):
                user = guild.get_member(int(match.group(1)))
            else:
                for member in guild.members:
                    display_name = member.display_name.lower()
                    base_name = member.name.lower()
                    if display_name.startswith(param_value_clean) or base_name.startswith(param_value_clean):
                        user = member
            if not user:
                raise CommandParamUserNotFoundException(self.name, param_value)
            return user
        elif self.type == Role:
            role = None
            if match := ROLE_MENTION_PATTERN.match(param_value.strip()):
                role = guild.get_role(int(match.group(1)))
            else:
                for guild_role in guild.roles:
                    if guild_role.name.lower().startswith(param_value_clean):
                        role = guild_role
            if not role:
                raise CommandParamRoleNotFoundException(self.name, param_value)
            return role
        elif self.type == TextChannel:
            channel = None
            if match := CHANNEL_MENTION_PATTERN.match(param_value.strip()):
                channel = guild.get_channel(int(match.group(1)))
            else:
                for guild_channel in guild.channels:
                    if (
                            isinstance(guild_channel, TextChannel)
                            and guild_channel.name.lower().startswith(param_value_clean)
                    ):
                        channel = guild_channel
            if not channel:
                raise CommandParamChannelNotFoundException(self.name, param_value)
            return channel

        raise TypeError(f'Invalid type "{self.type}" for param {self.name}')


class Command:
    callback: Callable
    callback_args: tuple[str, ...]
    name: str
    help_msg: str
    hidden: bool
    requires_gm: bool
    requires_player: bool
    use_context: bool
    params: list[CommandParam]

    def __init__(
            self,
            callback: Callable,
            callback_args: tuple[str, ...],
            name: str,
            help_msg: str,
            hidden: bool,
            requires_gm: bool,
            requires_player: bool,
            use_context: bool,
            params: list[CommandParam],
    ):
        if not inspect.isasyncgenfunction(callback) and not inspect.iscoroutinefunction(callback):
            raise TypeError("Command callback must be a coroutine.")

        self.callback = callback  # type: ignore
        self.callback_args = callback_args
        self.name = name
        self.help_msg = help_msg
        self.hidden = hidden
        self.requires_gm = requires_gm
        self.requires_player = requires_player
        self.use_context = use_context
        self.params = params

    def __call__(self, *args: Any, **kwargs: Any) -> Union[AsyncIterable, Coroutine]:
        return self.callback(*args, **kwargs)

    def __str__(self) -> str:
        params = [
            f"` `{'*' if not param.required else ''}`{param.name}`{'*' if not param.required else ''}"
            f"{'`...`' if param.collect else ''}"
            for param in self.params
        ]
        return f"**`{COMMAND_PREFIX}{self.name}`**{''.join(params).replace('``', '')}: {self.help_msg}"


@dataclass(frozen=True)
class CommandCallContext:
    channel: TextChannel
    guild: Guild
    member: Member
    message: Message

    def get_game(self, session: Session) -> Game:
        assert self.message.guild
        return get_or_create_game(
            session,
            self.message.guild  # type: ignore
        )


@dataclass(frozen=True)
class CommandCall:
    command: Command
    raw_param_values: str

    async def invoke(self, message: Message) -> AsyncIterable[CommandCallResponse]:
        args = []
        parsed_params = self.parse_params(
            message.guild  # type: ignore
        )
        for callback_arg in self.command.callback_args:
            if callback_arg == CONTEXT_ARG:
                args.append(
                    CommandCallContext(
                        channel=message.channel,
                        guild=message.guild,  # type: ignore
                        member=message.author,
                        message=message,
                    )
                )
            else:
                if callback_arg in parsed_params:
                    param_value = parsed_params[callback_arg]
                    if isinstance(param_value, tuple):
                        args.extend(param_value)
                    else:
                        args.append(param_value)
        invoked_command = self.command(*args)
        if inspect.iscoroutine(invoked_command):
            response = self.process_result(await invoked_command)  # type: ignore
            if response:
                yield response
        elif inspect.isasyncgen(invoked_command):
            async for result in invoked_command:  # type: ignore
                response = self.process_result(result)
                if response:
                    yield response
        else:
            raise TypeError(f'Invalid command result type "{invoked_command.__class__.__name__}"')

    @staticmethod
    def process_result(result: Optional[Union[str, CommandCallResponse]]) -> Optional[CommandCallResponse]:
        if result is None:
            return None
        elif isinstance(result, str):
            return CommandCallResponse(text=result)
        elif isinstance(result, CommandCallResponse):
            return result
        else:
            raise TypeError(f"Invalid response type: {result.__class__.__name__}")

    def parse_params(self, guild: Guild) -> dict[str, Any]:
        parsed_params = {}

        # Messy code to primitively try to handle quoted strings
        # The last argument is always taken entirely as-is, quotes included
        # A param can be specified to "collect" values, which will cause it to collect all remaining
        # whitespace-separated values into one tuple
        idx = 0
        clean_params = self.raw_param_values.strip()
        clean_params_length = len(clean_params)
        for i, param in enumerate(self.command.params):
            is_last = i == (len(self.command.params) - 1)
            param_value_elements = []
            while idx < clean_params_length:
                if is_last and not param.collect:
                    param_value_element, idx = clean_params[idx:], clean_params_length
                else:
                    param_value_element, idx = _get_param_value(clean_params, idx)
                param_value_elements.append(param_value_element)
                if not param.collect:
                    break

            if param.required and not param_value_elements:
                raise CommandParamMissingException(param.name)
            if param_value_elements:
                parsed_params[param.name] = param.parse(
                    guild, param_value_elements if param.collect else param_value_elements[0]
                )

        return parsed_params


def command(
        help_msg: str, hidden: bool = False, requires_gm: bool = False, requires_player: bool = False
) -> Callable:
    def wrapper(func: Callable) -> Callable:
        cmd_params = []
        signature = inspect.signature(func)
        use_context = False
        callback_args = []
        for parameter in signature.parameters.values():
            if parameter.name in ("self", "cls"):
                continue

            # Store the order of parameters so that we can pass arguments in order afterwards
            callback_args.append(parameter.name)

            if parameter.name == CONTEXT_ARG:
                use_context = True
                continue

            param_type: Type
            if parameter.annotation == parameter.empty:
                raise ValueError(f'Missing annotation on parameter "{parameter.name}" for command "{func.__name__}"')
            elif parameter.annotation in (str, Optional[str]):
                param_type = str
            elif parameter.annotation in (bool, Optional[bool]):
                param_type = bool
            elif parameter.annotation in (int, Optional[int]):
                param_type = int
            elif parameter.annotation in (Member, Optional[Member]):
                param_type = Member
            elif parameter.annotation in (Role, Optional[Role]):
                param_type = Role
            elif parameter.annotation in (TextChannel, Optional[TextChannel]):
                param_type = TextChannel
            else:
                raise ValueError(f'Invalid annotation on parameter "{parameter.name}" for command "{func.__name__}"')
            cmd_params.append(
                CommandParam(
                    name=parameter.name,
                    type=param_type,  # type: ignore
                    required=parameter.default == parameter.empty,
                    collect=parameter.kind == parameter.VAR_POSITIONAL
                )
            )

        func.command_metadata = Command(  # type: ignore
            callback=func,
            callback_args=tuple(callback_args),
            name=func.__name__.replace("_", ""),
            help_msg=help_msg,
            hidden=hidden,
            requires_gm=requires_gm,
            requires_player=requires_player,
            use_context=use_context,
            params=cmd_params,
        )
        return func

    return wrapper


def is_possible_command(message: Message) -> bool:
    return message.content.startswith(COMMAND_PREFIX)


def parse_message_as_command_call(commands: dict[str, Command], message: Message) -> Optional[CommandCall]:
    # Check whether this is a regular message first; if it is, ignore it
    msg: str = message.content
    if not is_possible_command(message):
        return None

    # Identify the command
    msg_split = msg[1:].split(" ", 1)
    name = msg_split[0]
    raw_param_values = msg_split[1] if len(msg_split) > 1 else ""

    return CommandCall(command=commands[name], raw_param_values=raw_param_values) if name in commands else None


def _get_param_value(string: str, idx: int) -> tuple[str, int]:
    idx = _consume_whitespace(string, idx)
    c = string[idx]
    if c == '"':
        idx += 1
        param, idx = _consume_until(string, idx, '"')
        idx += 1
        if idx < len(string) and string[idx] != " ":
            raise CommandException(f'Invalid parameters: {string}')
    else:
        param, idx = _consume_until(string, idx, ' ')
    return param, idx


def _consume_whitespace(string: str, idx: int) -> int:
    while idx < len(string) and string[idx] == ' ':
        idx += 1
    return idx


def _consume_until(string: str, idx: int, char: str) -> tuple[str, int]:
    bit = ''
    while idx < len(string) and string[idx] != char:
        bit += string[idx]
        idx += 1
    return bit, idx
