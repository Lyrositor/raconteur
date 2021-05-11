import http
import re
from collections import defaultdict
from typing import Optional, Any, Callable

from fastapi import APIRouter, Form
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import RedirectResponse

from raconteur.models.base import get_session
from raconteur.plugins.character.models import Character, CHARACTER_NAME_MAX_LENGTH, CHARACTER_STATUS_MAX_LENGTH, \
    CHARACTER_APPEARANCE_MAX_LENGTH, Location, LOCATION_DESCRIPTION_MAX_LENGTH, LOCATION_CATEGORY_MAX_LENGTH, \
    LOCATION_NAME_MAX_LENGTH, Connection
from raconteur.web.context import RequestContext
from raconteur.web.templates import render_response
from raconteur.web.utils import check_permissions, VALIDATION_ERRORS, add_validation_errors

LOCATION_NAME_PATTERN = re.compile(r"^[a-z0-9\-]*$")

character_plugin_router = APIRouter()


@character_plugin_router.get("/{current_game_id}/character/all")
async def characters_all(request: Request, current_game_id: int):
    with get_session() as session:
        context = await RequestContext.build(session, request, current_game_id)
        context.extra["characters"] = Character.get_all_of_guild(session, current_game_id)
        return render_response("character/all.html", context)


@character_plugin_router.get("/{current_game_id}/character/yours")
async def characters_yours(request: Request, current_game_id: int):
    with get_session() as session:
        context = await RequestContext.build(session, request, current_game_id)
        if await check_permissions(context, require_player=True):
            context.extra["characters"] = Character.get_all_of_member(session, current_game_id, context.current_user.id)
        return render_response("character/yours.html", context)


@character_plugin_router.get("/{current_game_id}/character/yours/new")
async def characters_yours_new(request: Request, current_game_id: int):
    return await _edit_entity(
        template="character/yours_edit.html",
        request=request,
        game_id=current_game_id,
        context_entity_key="character",
        fetch_func=lambda session, context: Character(),
        require_player=True,
    )


@character_plugin_router.post("/{current_game_id}/character/yours/new")
async def characters_yours_new(
        request: Request,
        current_game_id: int,
        name: str = Form(""),
        status: str = Form(""),
        appearance: str = Form(""),
        portrait: str = Form(""),
):
    return await _edit_entity(
        template="character/yours_edit.html",
        request=request,
        game_id=current_game_id,
        context_entity_key="character",
        fetch_func=lambda session, context: Character(),
        populate_func=_populate_character,
        redirect="characters_yours_edit",
        redirect_id_field="character_id",
        require_player=True,
        name=name,
        status=status,
        appearance=appearance,
        portrait=portrait,
    )


@character_plugin_router.get("/{current_game_id}/character/yours/edit/{character_id}")
async def characters_yours_edit(request: Request, current_game_id: int, character_id: int):
    return await _edit_entity(
        template="character/yours_edit.html",
        request=request,
        game_id=current_game_id,
        context_entity_key="character",
        fetch_func=lambda session, context: Character.get(
            session, current_game_id, context.current_user.id, character_id
        ),
        require_player=True,
    )


@character_plugin_router.post("/{current_game_id}/character/yours/edit/{character_id}")
async def characters_yours_edit(
        request: Request,
        current_game_id: int,
        character_id: int,
        name: str = Form(""),
        status: str = Form(""),
        appearance: str = Form(""),
        portrait: str = Form(""),
):
    return await _edit_entity(
        template="character/yours_edit.html",
        request=request,
        game_id=current_game_id,
        context_entity_key="character",
        fetch_func=lambda session, context: Character.get(
            session, current_game_id, context.current_user.id, character_id
        ),
        populate_func=_populate_character,
        require_player=True,
        name=name,
        status=status,
        appearance=appearance,
        portrait=portrait,
    )


@character_plugin_router.post("/{current_game_id}/character/yours/delete/{character_id}")
async def characters_yours_delete(request: Request, current_game_id: int, character_id: int):
    with get_session() as session:
        context = await RequestContext.build(session, request, current_game_id)
        if await check_permissions(context, require_player=True):
            if character := Character.get(session, current_game_id, context.current_user.id, character_id):
                session.delete(character)
                session.commit()
            else:
                context.errors.append("Failed to locate entity")
        return RedirectResponse(
            request.url_for("characters_yours", current_game_id=current_game_id),
            status_code=int(http.HTTPStatus.SEE_OTHER),
        )


@character_plugin_router.get("/{current_game_id}/character/locations")
async def characters_locations(request: Request, current_game_id: int):
    with get_session() as session:
        context = await RequestContext.build(session, request, current_game_id)
        if await check_permissions(context, require_gm=True):
            context.extra["locations"] = Location.get_all(session, guild_id=current_game_id)
        return render_response("character/locations.html", context)


@character_plugin_router.get("/{current_game_id}/character/locations/new")
async def characters_locations_new(request: Request, current_game_id: int):
    return await _edit_entity(
        template="character/locations_edit.html",
        request=request,
        game_id=current_game_id,
        context_entity_key="location",
        fetch_func=lambda session, context: Location(),
        require_gm=True,
    )


@character_plugin_router.post("/{current_game_id}/character/locations/new")
async def characters_locations_new(
        request: Request,
        current_game_id: int,
        name: str = Form(""),
        category: str = Form(""),
        description: str = Form(""),
):
    return await _edit_entity(
        template="character/locations_edit.html",
        request=request,
        game_id=current_game_id,
        context_entity_key="location",
        fetch_func=lambda session, context: Location(),
        populate_func=_populate_location,
        redirect="characters_locations_edit",
        redirect_id_field="location_id",
        require_gm=True,
        name=name,
        category=category,
        description=description
    )


@character_plugin_router.get("/{current_game_id}/character/locations/edit/{location_id}")
async def characters_locations_edit(request: Request, current_game_id: int, location_id: int):
    return await _edit_entity(
        template="character/locations_edit.html",
        request=request,
        game_id=current_game_id,
        context_entity_key="location",
        fetch_func=lambda session, context: _fetch_location(session, context, location_id),
        require_gm=True,
    )


@character_plugin_router.post("/{current_game_id}/character/locations/edit/{location_id}")
async def characters_locations_edit(
        request: Request,
        current_game_id: int,
        location_id: int,
        action: str = Form(""),

        name: str = Form(""),
        category: str = Form(""),
        description: str = Form(""),

        connection_id: Optional[int] = Form(None),
        other_location_id: Optional[int] = Form(None),
        timer: int = Form(0),
        locked: bool = Form(False),
        hidden: bool = Form(False),
):
    common_params = dict(
        template="character/locations_edit.html",
        request=request,
        game_id=current_game_id,
        context_entity_key="location",
        fetch_func=lambda session, context: _fetch_location(session, context, location_id),
        require_gm=True,
    )

    if action == "edit_location":
        return await _edit_entity(
            **common_params,
            populate_func=_populate_location,
            name=name,
            category=category,
            description=description
        )
    elif action == "add_connection":
        return await _edit_entity(
            **common_params,
            populate_func=_add_connection,
            other_location_id=other_location_id,
            timer=timer,
            locked=locked,
            hidden=hidden,
        )
    elif action == "edit_connection":
        return await _edit_entity(
            **common_params,
            populate_func=_edit_connection,
            connection_id=connection_id,
            timer=timer,
            locked=locked,
            hidden=hidden,
        )
    elif action == "delete_connection":
        return await _edit_entity(
            **common_params,
            populate_func=_delete_connection,
            connection_id=connection_id,
        )
    else:
        raise ValueError(f"Invalid action: {action}")


@character_plugin_router.post("/{current_game_id}/character/locations/delete/{location_id}")
async def characters_locations_delete(request: Request, current_game_id: int, location_id: int):
    with get_session() as session:
        context = await RequestContext.build(session, request, current_game_id)
        if await check_permissions(context, require_gm=True):
            if location := Location.get(session, current_game_id, location_id):
                session.delete(location)
                session.commit()
            else:
                context.errors.append("Failed to locate entity")
        return RedirectResponse(
            request.url_for("characters_locations", current_game_id=current_game_id),
            status_code=int(http.HTTPStatus.SEE_OTHER),
        )


async def _edit_entity(
        template: str,
        request: Request,
        game_id: id,
        context_entity_key: str,
        fetch_func: Callable,
        populate_func: Optional[Callable] = None,
        redirect: Optional[str] = None,
        redirect_id_field: Optional[str] = None,
        require_gm: bool = False,
        require_player: bool = False,
        require_spectator: bool = False,
        **data: Any
):
    with get_session() as session:
        context = await RequestContext.build(session, request, game_id)
        _add_constants(context)
        if await check_permissions(
                context, require_gm=require_gm, require_player=require_player, require_spectator=require_spectator
        ):
            entity = fetch_func(session, context)
            context.extra[context_entity_key] = entity
            if entity:
                if populate_func:
                    populate_func(session, context, entity, **data)
                    if not context.extra.get(VALIDATION_ERRORS):
                        session.add(entity)
                        session.commit()
                        if redirect and redirect_id_field:
                            return RedirectResponse(
                                request.url_for(
                                    redirect,
                                    current_game_id=context.current_game.guild_id,
                                    **{redirect_id_field: entity.id}
                                ),
                                status_code=int(http.HTTPStatus.SEE_OTHER),
                            )
            else:
                context.errors.append("Failed to locate entity")
        return render_response(template, context)


def _add_constants(context: RequestContext) -> None:
    context.extra.update(dict(
        character_name_max_length=CHARACTER_NAME_MAX_LENGTH,
        character_status_max_length=CHARACTER_STATUS_MAX_LENGTH,
        character_appearance_max_length=CHARACTER_APPEARANCE_MAX_LENGTH,
        location_name_max_length=LOCATION_NAME_MAX_LENGTH,
        location_category_max_length=LOCATION_CATEGORY_MAX_LENGTH,
        location_description_max_length=LOCATION_DESCRIPTION_MAX_LENGTH,
    ))


# noinspection PyUnusedLocal
def _populate_character(
        session: Session,
        context: RequestContext,
        character: Character,
        name: str,
        portrait: str,
        status: str,
        appearance: str,
) -> Character:
    character.game_guild_id = context.current_game.guild_id
    character.member_id = context.current_user.id
    character.name = name.strip()
    character.portrait = portrait.strip()
    character.status = status.strip()
    character.appearance = appearance.strip()

    validation_errors = []
    if not character.name:
        validation_errors.append("You must specify a name")
    if len(character.name) > CHARACTER_NAME_MAX_LENGTH:
        validation_errors.append(
            f"Character name is too long (must be {CHARACTER_NAME_MAX_LENGTH} characters or less)"
        )
    if (
            (existing_character := Character.get_by_name(session, context.current_game.guild_id, character.name))
            and existing_character != character
    ):
        validation_errors.append("A character with this name already exists")
    if len(character.status) > CHARACTER_STATUS_MAX_LENGTH:
        validation_errors.append(
            f"Character status is too long (must be {CHARACTER_STATUS_MAX_LENGTH} characters or less)"
        )
    if len(character.appearance) > CHARACTER_APPEARANCE_MAX_LENGTH:
        validation_errors.append(
            f"Character appearance is too long (must be {CHARACTER_APPEARANCE_MAX_LENGTH} characters or less)"
        )
    # noinspection HttpUrlsUsage
    if character.portrait and not (
            (character.portrait.startswith("http://") or character.portrait.startswith("https://"))
            and (
                    character.portrait.endswith(".png")
                    or character.portrait.endswith(".jpg")
                    or character.portrait.endswith(".jpeg")
                    or character.portrait.endswith(".gif")
            )
    ):
        validation_errors.append("You must specify a valid image URL (PNG, JPG or GIF)")

    add_validation_errors(context, validation_errors)

    return character


def _populate_location(
        session: Session,
        context: RequestContext,
        location: Location,
        name: str,
        category: str,
        description: str,
) -> Location:
    location.game_guild_id = context.current_game.guild_id
    location.name = name.strip()
    location.category = category.strip()
    location.description = description.strip()

    validation_errors = []
    if not location.name:
        validation_errors.append("You must specify a name")
    if len(location.name) > LOCATION_NAME_MAX_LENGTH:
        validation_errors.append(
            f"Location name is too long (must be {LOCATION_NAME_MAX_LENGTH} characters or less)"
        )
    if not LOCATION_NAME_PATTERN.match(location.name):
        validation_errors.append("Location name must consist only of lowercase letters, numbers and dashes")
    if (
            (existing_location := Location.get_by_name(session, context.current_game.guild_id, location.name))
            and existing_location != location
    ):
        validation_errors.append("A location with this name already exists")
    if not location.category:
        validation_errors.append("You must specify a category")
    if len(location.category) > LOCATION_CATEGORY_MAX_LENGTH:
        validation_errors.append(
            f"Location category is too long (must be {LOCATION_CATEGORY_MAX_LENGTH} characters or less)"
        )
    if not location.description:
        validation_errors.append("You must specify a description")
    if len(location.description) > LOCATION_DESCRIPTION_MAX_LENGTH:
        validation_errors.append(
            f"Location description is too long (must be {LOCATION_DESCRIPTION_MAX_LENGTH} characters or less)"
        )

    add_validation_errors(context, validation_errors)

    return location


def _add_connection(
        session: Session,
        context: RequestContext,
        location: Location,
        other_location_id: int,
        timer: int,
        locked: bool,
        hidden: bool,
) -> Location:
    validation_errors = []
    other_location = Location.get(session, context.current_game.guild_id, other_location_id)
    if timer < 0:
        validation_errors.append("Timer time cannot be negative")
    if other_location:
        for connection in location.connections_1 + location.connections_2:
            if connection.location_1 == other_location or connection.location_2 == other_location:
                validation_errors.append(f"A connection to {other_location.name} already exists")
                break
    else:
        validation_errors.append("Failed to locate location for connection")

    if not validation_errors:
        connection = Connection()
        connection.location_2 = other_location
        connection.timer = timer
        connection.locked = locked
        connection.hidden = hidden
        location.connections_1.append(connection)
        session.add(connection)
    else:
        # Re-populate the form if it failed, so it can be adjusted by the user
        context.extra.update(dict(
            connection_new_other_location_id=other_location_id,
            connection_new_timer=timer,
            connection_new_locked=locked,
            connection_new_hidden=hidden,
        ))

    add_validation_errors(context, validation_errors)

    return location


# noinspection PyUnusedLocal
def _edit_connection(
        session: Session,
        context: RequestContext,
        location: Location,
        connection_id: Optional[int],
        timer: int,
        locked: bool,
        hidden: bool,
) -> Location:
    validation_errors = []
    for connection in location.connections_1 + location.connections_2:
        if connection.id == connection_id:
            connection.timer = timer
            connection.locked = locked
            connection.hidden = hidden
            break
    else:
        validation_errors.append("Failed to locate connection")
    if timer < 0:
        validation_errors.append("Timer time cannot be negative")

    add_validation_errors(context, validation_errors)

    return location


# noinspection PyUnusedLocal
def _delete_connection(
        session: Session,
        context: RequestContext,
        location: Location,
        connection_id: Optional[int],
) -> Location:
    for connection in list(location.connections_1):
        if connection.id == connection_id:
            location.connections_1.remove(connection)
            return location
    for connection in list(location.connections_2):
        if connection.id == connection_id:
            location.connections_2.remove(connection)
            return location

    add_validation_errors(context, ["Failed to locate connection"])
    return location


def _fetch_location(session: Session, context: RequestContext, location_id: int) -> Optional[Location]:
    context.extra["other_locations"] = defaultdict(list)
    if location := Location.get(session, context.current_game.guild_id, location_id):
        for other_location in Location.get_all(session, context.current_game.guild_id):
            if other_location.id != location.id:
                context.extra["other_locations"][other_location.category].append(other_location)
    return location
