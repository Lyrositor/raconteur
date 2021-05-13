from raconteur.web.context import RequestContext

VALIDATION_ERRORS = "validation_errors"


async def check_permissions(
        context: RequestContext,
        required_logged_in: bool = False,
        require_gm: bool = False,
        require_player: bool = False,
        require_spectator: bool = False
) -> bool:
    if not context.current_game:
        context.errors.append("You must specified a valid game")
    if required_logged_in and context.current_user:
        context.errors.append("You must be logged in to view this page")
    if require_gm and not context.permissions.is_gm:
        context.errors.append("You must be a GM to view this page")
    if require_player and not context.permissions.is_player:
        context.errors.append("You must be a player to view this page")
    if require_spectator and not context.permissions.is_spectator:
        context.errors.append("You must be a spectator to view this page")
    if context.errors:
        return False
    return True


def add_validation_errors(context: RequestContext, validation_errors: list[str]) -> None:
    if VALIDATION_ERRORS not in context.extra:
        context.extra[VALIDATION_ERRORS] = []
    context.extra[VALIDATION_ERRORS].extend(validation_errors)
