import http
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import Response, RedirectResponse

from raconteur.models.base import get_session
from raconteur.plugins.character.models import Character
from raconteur.plugins.unknown_armies.models import UnknownArmiesSheet, UnknownArmiesMadness, UnknownArmiesAbility, \
    UnknownArmiesSkill
from raconteur.web.context import RequestContext
from raconteur.web.templates import render_response
from raconteur.web.utils import check_permissions

unknown_armies_router = APIRouter()


class UnknownArmiesSkillForm(BaseModel):
    id: Optional[int] = None
    ability: UnknownArmiesAbility = UnknownArmiesAbility.BODY
    name: str = ""
    value: int = 0
    is_obsession: bool = False


class UnknownArmiesSheetForm(BaseModel):
    is_editing: bool = False
    character_id: Optional[int] = None

    summary: str = ""
    personality: str = ""
    obsession: str = ""
    school: Optional[str] = None
    stimulus_fear_madness: UnknownArmiesMadness = UnknownArmiesMadness.VIOLENCE
    stimulus_fear: str = ""
    stimulus_rage: str = ""
    stimulus_noble: str = ""

    # Abilities
    body: int = 0
    body_descriptor: str = ""
    speed: int = 0
    speed_descriptor: str = ""
    mind: int = 0
    mind_descriptor: str = ""
    soul: int = 0
    soul_descriptor: str = ""

    # Skills
    xp: int = 0
    skills: list[UnknownArmiesSkillForm] = []

    # Stress
    violence_hardened: int = 0
    violence_failed: int = 0
    unnatural_hardened: int = 0
    unnatural_failed: int = 0
    helplessness_hardened: int = 0
    helplessness_failed: int = 0
    isolation_hardened: int = 0
    isolation_failed: int = 0
    self_hardened: int = 0
    self_failed: int = 0


class UnknownArmiesSheetResponse(BaseModel):
    success: bool = False
    errors: list[str] = []
    redirect: Optional[str] = None


@unknown_armies_router.get("/{current_game_id}/unknown_armies/list")
async def ua_list(request: Request, current_game_id: int) -> Response:
    with get_session() as session:
        context = await RequestContext.build(session, request, current_game_id)
        if await check_permissions(context, require_player=True):
            assert context.current_user
            context.extra["sheets"] = UnknownArmiesSheet.get_all_of_member(
                session, current_game_id, context.current_user.id
            )
            context.extra["characters"] = Character.get_all_of_member(session, current_game_id, context.current_user.id)
        return render_response("unknown_armies/list.html", context)


@unknown_armies_router.get("/{current_game_id}/unknown_armies/new")
async def ua_new(request: Request, current_game_id: int) -> Response:
    with get_session() as session:
        context = await RequestContext.build(session, request, current_game_id)
        if await check_permissions(context, require_player=True):
            _setup_context(session, context)
            context.extra["sheet"] = UnknownArmiesSheetForm()
        return render_response("unknown_armies/edit.html", context)


@unknown_armies_router.get("/{current_game_id}/unknown_armies/edit/{character_id}")
async def ua_edit(request: Request, current_game_id: int, character_id: int) -> Response:
    with get_session() as session:
        context = await RequestContext.build(session, request, current_game_id)
        if await check_permissions(context, require_player=True):
            if model := UnknownArmiesSheet.get(session, current_game_id, context.current_user.id, character_id):
                _setup_context(session, context)
                context.extra["sheet"] = UnknownArmiesSheetForm(is_editing=True)
                _populate_form(model, context.extra["sheet"])
            else:
                context.errors.append("Failed to locate entity")

        return render_response("unknown_armies/edit.html", context)


@unknown_armies_router.post("/{current_game_id}/unknown_armies/delete/{character_id}")
async def ua_delete(request: Request, current_game_id: int, character_id: int) -> Response:
    with get_session() as session:
        context = await RequestContext.build(session, request, current_game_id)
        if await check_permissions(context, require_player=True):
            if model := UnknownArmiesSheet.get(session, current_game_id, context.current_user.id, character_id):
                session.delete(model)
                session.commit()
            else:
                context.errors.append("Failed to locate entity")
    return RedirectResponse(
        request.url_for(ua_list.__name__, current_game_id=current_game_id),
        status_code=int(http.HTTPStatus.SEE_OTHER),
    )


@unknown_armies_router.post("/{current_game_id}/unknown_armies/sheet", response_model=UnknownArmiesSheetResponse)
async def ua_sheet(request: Request, current_game_id: int, sheet: UnknownArmiesSheetForm) -> UnknownArmiesSheetResponse:
    response = UnknownArmiesSheetResponse()
    with get_session() as session:
        context = await RequestContext.build(session, request, current_game_id)
        if not await check_permissions(context, require_player=True):
            response.errors.append("You must be a player to edit character sheets.")
            return response
        if sheet.character_id is None:
            response.errors.append("You must specify a character.")
        else:
            character = Character.get(session, current_game_id, context.current_user.id, sheet.character_id)
            if not character:
                response.errors.append("Failed to locate character.")

        if sheet.body < 0 or sheet.body > 100:
            response.errors.append("Your Body score must be between 0 and 100.")
        if sheet.speed < 0 or sheet.speed > 100:
            response.errors.append("Your Speed score must be between 0 and 100.")
        if sheet.mind < 0 or sheet.mind > 100:
            response.errors.append("Your Mind score must be between 0 and 100.")
        if sheet.soul < 0 or sheet.soul > 100:
            response.errors.append("Your Soul score must be between 0 and 100.")

        if sheet.xp < 0:
            response.errors.append("Your XP cannot be negative.")

        if sheet.violence_hardened < 0 or sheet.violence_hardened > 10:
            response.errors.append("Your Violence (Hardened) score must be between 0 and 10.")
        if sheet.violence_failed < 0 or sheet.violence_failed > 5:
            response.errors.append("Your Violence (Failed) score must be between 0 and 5.")

        if sheet.unnatural_hardened < 0 or sheet.unnatural_hardened > 10:
            response.errors.append("Your Unnatural (Hardened) score must be between 0 and 10.")
        if sheet.unnatural_failed < 0 or sheet.unnatural_failed > 5:
            response.errors.append("Your Unnatural (Failed) score must be between 0 and 5.")

        if sheet.helplessness_hardened < 0 or sheet.helplessness_hardened > 10:
            response.errors.append("Your Helplessness (Hardened) score must be between 0 and 10.")
        if sheet.helplessness_failed < 0 or sheet.helplessness_failed > 5:
            response.errors.append("Your Helplessness (Failed) score must be between 0 and 5.")

        if sheet.isolation_hardened < 0 or sheet.isolation_hardened > 10:
            response.errors.append("Your Isolation (Hardened) score must be between 0 and 10.")
        if sheet.isolation_failed < 0 or sheet.isolation_failed > 5:
            response.errors.append("Your Isolation (Failed) score must be between 0 and 5.")

        if sheet.self_hardened < 0 or sheet.self_hardened > 10:
            response.errors.append("Your Self (Hardened) score must be between 0 and 10.")
        if sheet.self_failed < 0 or sheet.self_failed > 5:
            response.errors.append("Your Self (Failed) score must be between 0 and 5.")

        has_obsession_skill = 0
        for skill in sheet.skills:
            if skill.is_obsession:
                has_obsession_skill += 1
            if skill.value < 0 or skill.value > 100:
                response.errors.append(f"Your {skill.name} skill must be between 0 and 100.")
        if not has_obsession_skill:
            response.errors.append("You must choose an obsession skill.")
        elif has_obsession_skill > 1:
            response.errors.append("You can only choose one obsession skill.")

        model = UnknownArmiesSheet.get_for_character(session, sheet.character_id)
        if sheet.is_editing and not model:
            response.errors.append("No sheet to edit.")
        elif not sheet.is_editing and model:
            response.errors.append("A sheet for this character already exists.")

        if response.errors:
            return response

        if not model:
            model = UnknownArmiesSheet()
            session.add(model)

        _populate_model(model, sheet, current_game_id)
        session.commit()

        response.success = True
        response.redirect = request.url_for(
            ua_edit.__name__, current_game_id=current_game_id, character_id=character.id
        )
        return response


def _setup_context(session: Session, context: RequestContext) -> None:
    context.extra["characters"] = (
        (character.id, character.name) for character in
        Character.get_all_of_member(session, context.current_game.guild_id, context.current_user.id)
    )
    context.extra["abilities"] = [ability.value for ability in UnknownArmiesAbility]
    context.extra["madness"] = [madness.value for madness in UnknownArmiesMadness]


def _populate_model(model: UnknownArmiesSheet, form: UnknownArmiesSheetForm, current_game_id: int) -> None:
    model.game_guild_id = current_game_id
    model.character_id = form.character_id

    model.summary = form.summary
    model.personality = form.personality
    model.obsession = form.obsession
    model.school = form.school
    model.stimulus_fear_madness = form.stimulus_fear_madness
    model.stimulus_fear = form.stimulus_fear
    model.stimulus_rage = form.stimulus_rage
    model.stimulus_noble = form.stimulus_noble

    model.body = form.body
    model.body_descriptor = form.body_descriptor
    model.speed = form.speed
    model.speed_descriptor = form.speed_descriptor
    model.mind = form.mind
    model.mind_descriptor = form.mind_descriptor
    model.soul = form.soul
    model.soul_descriptor = form.soul_descriptor

    model.xp = form.xp

    for skill_model in model.skills:
        skill_model.is_obsession = False
    remaining_skill_models = []
    for skill in form.skills:
        for skill_model in model.skills:
            if skill_model.id is not None and skill.id == skill_model.id:
                remaining_skill_models.append(skill_model)
                break
        else:
            skill_model = UnknownArmiesSkill()
            skill_model.game_guild_id = current_game_id
            remaining_skill_models.append(skill_model)
            model.skills.append(skill_model)
        skill_model.name = skill.name
        skill_model.value = skill.value
        skill_model.ability = skill.ability
        skill_model.is_obsession = skill.is_obsession
    for skill_model in model.skills:
        if skill_model not in remaining_skill_models:
            model.skills.remove(skill_model)

    model.violence_hardened = form.violence_hardened
    model.violence_failed = form.violence_failed
    model.unnatural_hardened = form.unnatural_hardened
    model.unnatural_failed = form.unnatural_failed
    model.helplessness_hardened = form.helplessness_hardened
    model.helplessness_failed = form.helplessness_failed
    model.isolation_hardened = form.isolation_hardened
    model.isolation_failed = form.isolation_failed
    model.self_hardened = form.self_hardened
    model.self_failed = form.self_failed


def _populate_form(model: UnknownArmiesSheet, form: UnknownArmiesSheetForm) -> None:
    form.character_id = model.character_id

    form.summary = model.summary
    form.personality = model.personality
    form.obsession = model.obsession
    form.school = model.school
    form.stimulus_fear_madness = model.stimulus_fear_madness
    form.stimulus_fear = model.stimulus_fear
    form.stimulus_rage = model.stimulus_rage
    form.stimulus_noble = model.stimulus_noble

    form.body = model.body
    form.body_descriptor = model.body_descriptor
    form.speed = model.speed
    form.speed_descriptor = model.speed_descriptor
    form.mind = model.mind
    form.mind_descriptor = model.mind_descriptor
    form.soul = model.soul
    form.soul_descriptor = model.soul_descriptor

    form.xp = model.xp

    for model_skill in model.skills:
        form.skills.append(UnknownArmiesSkillForm(
            id=model_skill.id,
            name=model_skill.name,
            ability=model_skill.ability,
            value=model_skill.value,
            is_obsession=model_skill.is_obsession,
        ))

    form.violence_hardened = model.violence_hardened
    form.violence_failed = model.violence_failed
    form.unnatural_hardened = model.unnatural_hardened
    form.unnatural_failed = model.unnatural_failed
    form.helplessness_hardened = model.helplessness_hardened
    form.helplessness_failed = model.helplessness_failed
    form.isolation_hardened = model.isolation_hardened
    form.isolation_failed = model.isolation_failed
    form.self_hardened = model.self_hardened
    form.self_failed = model.self_failed
