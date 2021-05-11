class CommandException(Exception):
    pass


class CommandParamMissingException(CommandException):
    param_name: str

    def __init__(self, param_name: str):
        super().__init__(f'Missing parameter "{param_name}"')
        self.param_name = param_name


class CommandParamValueException(CommandException):
    param_name: str
    param_value: str

    def __init__(self, param_name: str, param_value: str):
        super().__init__(f'Invalid value "{param_value}" for parameter "{param_name}"')
        self.param_name = param_name
        self.param_value = param_value


class CommandParamUserNotFoundException(CommandException):
    def __init__(self, param_name: str, param_value: str):
        super().__init__(f'Failed to locate user "{param_value}" for parameter "{param_name}"')
        self.param_name = param_name
        self.param_value = param_value


class CommandParamRoleNotFoundException(CommandException):
    def __init__(self, param_name: str, param_value: str):
        super().__init__(f'Failed to locate role "{param_value}" for parameter "{param_name}"')
        self.param_name = param_name
        self.param_value = param_value


class CommandParamChannelNotFoundException(CommandException):
    def __init__(self, param_name: str, param_value: str):
        super().__init__(f'Failed to locate channel "{param_value}" for parameter "{param_name}"')
        self.param_name = param_name
        self.param_value = param_value
