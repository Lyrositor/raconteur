import http
from typing import Optional, Iterable

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import Response, RedirectResponse

from raconteur.models.base import get_session
from raconteur.plugins.character.models import Character
from raconteur.plugins.umbreal.constants import D6, D4, D8, D12, D10
from raconteur.plugins.umbreal.models import UmbrealSheet, UmbrealTrait, UmbrealTraitSet, UmbrealLawbreak
from raconteur.web.context import RequestContext
from raconteur.web.templates import render_response
from raconteur.web.utils import check_permissions

DEFAULT_ALLOWED_VALUES = (D4, D6, D8, D10, D12)
POWER_ALLOWED_VALUES = (0, D6, D8, D10, D12)
SIGNATURE_ASSET_ALLOWED_VALUES = (D6, D8, D10, D12)
NAME_MAX_LENGTH = 100
DESCRIPTION_MAX_LENGTH = 1000


class UmbrealSheetTraitForm(BaseModel):
    id: Optional[int] = None
    name: str = ""
    description: str = ""
    value: int = D4


class UmbrealSheetLawbreakForm(BaseModel):
    id: Optional[int] = None
    name: str = ""
    description: str = ""


class UmbrealSheetForm(BaseModel):
    is_editing: bool = False
    character_id: Optional[int] = None

    distinction_before_id: Optional[int] = None
    distinction_before_name: str = ""
    distinction_before_description: str = ""
    distinction_now_id: Optional[int] = None
    distinction_now_name: str = ""
    distinction_now_description: str = ""
    distinction_after_id: Optional[int] = None
    distinction_after_name: str = ""
    distinction_after_description: str = ""

    attribute_deftness: int = D4
    attribute_force: int = D4
    attribute_intellect: int = D4
    attribute_magnetism: int = D4
    attribute_perception: int = D4
    attribute_solidity: int = D4
    attribute_will: int = D4

    skill_ambulatorics: int = D4
    skill_antagonomics_melee: int = D4
    skill_antagonomics_ranged: int = D4
    skill_cartography: int = D4
    skill_cognitoscopy: int = D4
    skill_dissimulation: int = D4
    skill_dramaturgy: int = D4
    skill_engineering: int = D4
    skill_erudition: int = D4
    skill_fidophysics: int = D4
    skill_finespeech: int = D4
    skill_gadgetry: int = D4
    skill_oneiromancy: int = D4
    skill_perspiraction: int = D4
    skill_remedics: int = D4
    skill_steelthink: int = D4
    skill_vehiculation: int = D4

    power_denebulation: int = 0
    power_esodactyly: int = 0
    power_kleinsicht: int = 0
    power_lithargy: int = 0
    power_mementogenesis: int = 0
    power_morflexicity: int = 0
    power_sensartistry: int = 0
    power_subsonance: int = 0

    signature_assets: list[UmbrealSheetTraitForm] = [
        UmbrealSheetTraitForm(value=D6),
        UmbrealSheetTraitForm(value=D6),
    ]

    lawbreaks: list[UmbrealSheetLawbreakForm] = [
        UmbrealSheetLawbreakForm(
            name="Hinder",
            description="Gain a PP when you switch out a distinction's d8 for a d4."
        ),
        UmbrealSheetLawbreakForm(),
    ]

    xp_1_milestone: str = ""
    xp_3_milestone: str = ""
    xp_10_milestone: str = ""


class UmbrealSheetResponse(BaseModel):
    success: bool = False
    errors: list[str] = []
    redirect: Optional[str] = None


umbreal_router = APIRouter()


@umbreal_router.get("/{current_game_id}/umbreal/list")
async def umbreal_list(request: Request, current_game_id: int) -> Response:
    with get_session() as session:
        context = await RequestContext.build(session, request, current_game_id)
        if await check_permissions(context, require_player=True):
            assert context.current_user
            context.extra["sheets"] = UmbrealSheet.get_all_of_member(
                session, current_game_id, context.current_user.id
            )
            context.extra["characters"] = Character.get_all_of_member(session, current_game_id, context.current_user.id)
        return render_response("umbreal/list.html", context)


@umbreal_router.get("/{current_game_id}/umbreal/new")
async def umbreal_new(request: Request, current_game_id: int) -> Response:
    with get_session() as session:
        context = await RequestContext.build(session, request, current_game_id)
        if await check_permissions(context, require_player=True):
            _setup_context(session, context)
            context.extra["sheet"] = UmbrealSheetForm()
        return render_response("umbreal/edit.html", context)


@umbreal_router.get("/{current_game_id}/umbreal/edit/{character_id}")
async def umbreal_edit(request: Request, current_game_id: int, character_id: int) -> Response:
    with get_session() as session:
        context = await RequestContext.build(session, request, current_game_id)
        if await check_permissions(context, require_player=True):
            if model := UmbrealSheet.get(session, current_game_id, context.current_user.id, character_id):
                _setup_context(session, context)
                context.extra["sheet"] = UmbrealSheetForm(is_editing=True)
                _populate_form(model, context.extra["sheet"])
            else:
                context.errors.append("Failed to locate entity")

        return render_response("umbreal/edit.html", context)


@umbreal_router.post("/{current_game_id}/umbreal/delete/{character_id}")
async def umbreal_delete(request: Request, current_game_id: int, character_id: int) -> Response:
    with get_session() as session:
        context = await RequestContext.build(session, request, current_game_id)
        if await check_permissions(context, require_player=True):
            if model := UmbrealSheet.get(session, current_game_id, context.current_user.id, character_id):
                session.delete(model)
                session.commit()
            else:
                context.errors.append("Failed to locate entity")
    return RedirectResponse(
        request.url_for(umbreal_list.__name__, current_game_id=current_game_id),
        status_code=int(http.HTTPStatus.SEE_OTHER),
    )


@umbreal_router.post("/{current_game_id}/umbreal/sheet", response_model=UmbrealSheetResponse)
async def umbreal_sheet(request: Request, current_game_id: int, sheet: UmbrealSheetForm) -> UmbrealSheetResponse:
    response = UmbrealSheetResponse()
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

        response.errors.extend(_validate_form(sheet))

        model = UmbrealSheet.get_for_character(session, sheet.character_id)
        if sheet.is_editing and not model:
            response.errors.append("No sheet to edit.")
        elif not sheet.is_editing and model:
            response.errors.append("A sheet for this character already exists.")

        if response.errors:
            return response

        if not model:
            model = UmbrealSheet()
            session.add(model)

        _populate_model(model, sheet, current_game_id)
        session.commit()

        response.success = True
        response.redirect = request.url_for(
            umbreal_edit.__name__, current_game_id=current_game_id, character_id=character.id
        )
        return response


def _setup_context(session: Session, context: RequestContext) -> None:
    context.extra["characters"] = (
        (character.id, character.name) for character in
        Character.get_all_of_member(session, context.current_game.guild_id, context.current_user.id)
    )


def _validate_form(form: UmbrealSheetForm) -> Iterable[str]:
    for name, value in form:
        if name.startswith("distinction_"):
            if name.endswith("_name"):
                if not value:
                    yield f"Distinction name cannot be empty"
                if len(value) > NAME_MAX_LENGTH:
                    yield f"Distinction name must be less than {NAME_MAX_LENGTH} characters long"
            elif name.endswith("_description"):
                if not value:
                    yield f"Distinction description cannot be empty"
                if len(value) > DESCRIPTION_MAX_LENGTH:
                    yield f"Distinction description must be less than {DESCRIPTION_MAX_LENGTH} characters long"
        elif name.startswith("attribute_"):
            if value not in DEFAULT_ALLOWED_VALUES:
                yield "Invalid attribute value"
        elif name.startswith("skill_"):
            if value not in DEFAULT_ALLOWED_VALUES:
                yield "Invalid skill value"
        elif name.startswith("power_"):
            if value not in POWER_ALLOWED_VALUES:
                yield "Invalid power value"
        elif name == "signature_assets":
            for signature_asset in value:
                if not signature_asset.name:
                    yield "Signature asset name cannot be empty"
                if len(signature_asset.name) > NAME_MAX_LENGTH:
                    yield f"Signature asset name must be less than {NAME_MAX_LENGTH} characters long"
                if not signature_asset.description:
                    yield "Signature asset description cannot be empty"
                if len(signature_asset.description) > DESCRIPTION_MAX_LENGTH:
                    yield f"Signature asset description must be less than {DESCRIPTION_MAX_LENGTH} characters long"
                if signature_asset.value not in SIGNATURE_ASSET_ALLOWED_VALUES:
                    yield "Invalid signature asset value"
        elif name == "lawbreaks":
            for lawbreak in value:
                if not lawbreak.name:
                    yield "Lawbreak name cannot be empty"
                if len(lawbreak.name) > NAME_MAX_LENGTH:
                    yield f"Lawbreak name must be less than {NAME_MAX_LENGTH} characters long"
                if not lawbreak.description:
                    yield "Lawbreak description cannot be empty"
                if len(lawbreak.description) > DESCRIPTION_MAX_LENGTH:
                    yield f"Lawbreak description must be less than {DESCRIPTION_MAX_LENGTH} characters long"
        elif name.startswith("xp_"):
            if not value:
                yield "XP milestone level cannot be empty"
            if len(value) > DESCRIPTION_MAX_LENGTH:
                yield f"XP milestone level must be less than {DESCRIPTION_MAX_LENGTH} characters long"


def _populate_model(model: UmbrealSheet, form: UmbrealSheetForm, current_game_id: int) -> None:
    model.game_guild_id = current_game_id
    model.character_id = form.character_id

    _populate_model_distinctions(model, form)
    _populate_model_attributes(model, form)
    _populate_model_skills(model, form)
    _populate_model_powers(model, form)
    _populate_signature_assets(model, form)
    _populate_lawbreaks(model, form)

    model.xp_1_milestone = form.xp_1_milestone
    model.xp_3_milestone = form.xp_3_milestone
    model.xp_10_milestone = form.xp_10_milestone


def _populate_model_distinctions(model: UmbrealSheet, form: UmbrealSheetForm) -> None:
    distinction_before = _get_or_create_trait_by_id(model, UmbrealTraitSet.DISTINCTIONS, form.distinction_before_id)
    distinction_before.name = f"Before: {form.distinction_before_name}"
    distinction_before.description = form.distinction_before_description
    distinction_before.value = D8

    distinction_now = _get_or_create_trait_by_id(model, UmbrealTraitSet.DISTINCTIONS, form.distinction_now_id)
    distinction_now.name = f"Now: {form.distinction_now_name}"
    distinction_now.description = form.distinction_now_description
    distinction_now.value = D8

    distinction_after = _get_or_create_trait_by_id(model, UmbrealTraitSet.DISTINCTIONS, form.distinction_after_id)
    distinction_after.name = f"After: {form.distinction_after_name}"
    distinction_after.description = form.distinction_after_description
    distinction_after.value = D8


def _populate_model_attributes(model: UmbrealSheet, form: UmbrealSheetForm) -> None:
    attributes = [
        ("Deftness", "Agility, reactivity, delicate manipulations", form.attribute_deftness),
        ("Force", "Brute strength, athleticism", form.attribute_force),
        ("Intellect", "Logic, conceptualization, knowledge", form.attribute_intellect),
        ("Magnetism", "Charisma, guile", form.attribute_magnetism),
        ("Perception", "Awareness, recognition", form.attribute_perception),
        ("Solidity", "Resilience, vitality, physicality", form.attribute_solidity),
        ("Will", "Resolve, self-definition, courage", form.attribute_will),
    ]
    for name, description, value in attributes:
        attribute = _get_or_create_trait_by_name(model, UmbrealTraitSet.ATTRIBUTES, name)
        attribute.description = description
        attribute.value = value


def _populate_model_skills(model: UmbrealSheet, form: UmbrealSheetForm) -> None:
    skills = [
        ("Ambulatorics", "Running, jumping, climbing", form.skill_ambulatorics),
        ("Antagonomics (melee)", "Melee combat, fist fights, tackling", form.skill_antagonomics_melee),
        ("Antagonomics (ranged)", "Ranged combat, guns, external ship weaponry", form.skill_antagonomics_ranged),
        ("Cartography", "Navigation, carving light into shadow", form.skill_cartography),
        ("Cognitoscopy", "Psychiatry, shadowing detection", form.skill_cognitoscopy),
        ("Dissimulation", "Stealth, lies, deceit", form.skill_dissimulation),
        ("Dramaturgy", "Putting on a flashy show, distracting", form.skill_dramaturgy),
        ("Engineering", "Building and repairing machines", form.skill_engineering),
        ("Erudition", "Knowledge of specialized topics", form.skill_erudition),
        ("Fidophysics", "Engineering the laws of reality", form.skill_fidophysics),
        ("Finespeech", "Diplomacy, conflict resolution", form.skill_finespeech),
        ("Gadgetry", "Operating computers, devices, gadgets", form.skill_gadgetry),
        ("Oneiromancy", "Creating, tailoring, resisting dreams", form.skill_oneiromancy),
        ("Perspiraction", "Manual labor, lifting, pushing, digging, pulling, hauling", form.skill_perspiraction),
        ("Remedics", "Healing", form.skill_remedics),
        ("Steelthink", "Focus, meditation", form.skill_steelthink),
        ("Vehiculation", "Piloting, driving, vehicle knowledge", form.skill_vehiculation),
    ]
    for name, description, value in skills:
        skill = _get_or_create_trait_by_name(model, UmbrealTraitSet.SKILLS, name)
        skill.description = description
        skill.value = value


def _populate_model_powers(model: UmbrealSheet, form: UmbrealSheetForm) -> None:
    powers = [
        ("Denebulation", "Divination, interpretation of prophecies", form.power_denebulation),
        ("Esodactyly", "Telekinesis, remote sensation", form.power_esodactyly),
        ("Kleinsicht", "Senses-independent knowledge of one's surroundings", form.power_kleinsicht),
        ("Lithargy", "Immunity to reality's impositions", form.power_lithargy),
        ("Mementogenesis", "Creating, altering, deleting memories", form.power_mementogenesis),
        ("Morflexicity", "Altering one's body", form.power_morflexicity),
        ("Sensartistry", "Stimulation, synthesis of sensations", form.power_sensartistry),
        ("Subsonance", "Telepathy, thought inception", form.power_subsonance),
    ]
    for name, description, value in powers:
        power = _get_or_create_trait_by_name(model, UmbrealTraitSet.POWERS, name)
        power.description = description
        power.value = value


def _populate_signature_assets(model: UmbrealSheet, form: UmbrealSheetForm) -> None:
    signature_assets = []
    for signature_asset_form in form.signature_assets:
        signature_asset = _get_or_create_trait_by_id(model, UmbrealTraitSet.SIGNATURE_ASSETS, signature_asset_form.id)
        signature_asset.name = signature_asset_form.name
        signature_asset.description = signature_asset_form.description
        signature_asset.value = signature_asset_form.value
        signature_assets.append(signature_asset)
    for trait in model.traits:
        if trait.set == UmbrealTraitSet.SIGNATURE_ASSETS and trait not in signature_assets:
            model.traits.remove(trait)


def _populate_lawbreaks(model: UmbrealSheet, form: UmbrealSheetForm) -> None:
    lawbreaks = []
    for lawbreak_form in form.lawbreaks:
        lawbreak = _get_or_create_lawbreak_by_id(model, lawbreak_form.id)
        lawbreak.name = lawbreak_form.name
        lawbreak.description = lawbreak_form.description
        lawbreaks.append(lawbreak)
    model.lawbreaks[:] = lawbreaks


def _get_or_create_trait_by_id(
        model: UmbrealSheet, trait_set: UmbrealTraitSet, trait_id: Optional[int]
) -> UmbrealTrait:
    for trait in model.traits:
        if trait.set == trait_set and trait_id is not None and trait.id == trait_id:
            return trait
    else:
        trait = UmbrealTrait()
        trait.id = trait_id
        trait.game_guild_id = model.game_guild_id
        trait.set = trait_set
        model.traits.append(trait)
        return trait


def _get_or_create_trait_by_name(model: UmbrealSheet, trait_set: UmbrealTraitSet, name: str) -> UmbrealTrait:
    for trait in model.traits:
        if trait.set == trait_set and trait.name == name:
            return trait
    else:
        trait = UmbrealTrait()
        trait.game_guild_id = model.game_guild_id
        trait.name = name
        trait.set = trait_set
        model.traits.append(trait)
        return trait


def _get_or_create_lawbreak_by_id(model: UmbrealSheet, lawbreak_id: Optional[int]) -> UmbrealLawbreak:
    for lawbreak in model.lawbreaks:
        if lawbreak_id is not None and lawbreak.id == lawbreak_id:
            return lawbreak
    else:
        lawbreak = UmbrealLawbreak()
        lawbreak.id = lawbreak_id
        lawbreak.game_guild_id = model.game_guild_id
        model.lawbreaks.append(lawbreak)
        return lawbreak


def _populate_form(model: UmbrealSheet, form: UmbrealSheetForm) -> None:
    form.character_id = model.character_id
    form.signature_assets = []
    form.lawbreaks = []

    for trait in model.traits:
        clean_name = trait.name.lower().replace("(", "").replace(")", "").replace(" ", "_")
        if trait.set == UmbrealTraitSet.DISTINCTIONS:
            tag, actual_name = trait.name.split(": ", maxsplit=1)
            setattr(form, f"distinction_{tag.lower()}_id", trait.id)
            setattr(form, f"distinction_{tag.lower()}_name", actual_name)
            setattr(form, f"distinction_{tag.lower()}_description", trait.description)
        elif trait.set == UmbrealTraitSet.ATTRIBUTES:
            setattr(form, f"attribute_{clean_name}", trait.value)
        elif trait.set == UmbrealTraitSet.SKILLS:
            setattr(form, f"skill_{clean_name}", trait.value)
        elif trait.set == UmbrealTraitSet.POWERS:
            setattr(form, f"power_{clean_name}", trait.value)
        elif trait.set == UmbrealTraitSet.SIGNATURE_ASSETS:
            form.signature_assets.append(
                UmbrealSheetTraitForm(id=trait.id, name=trait.name, description=trait.description, value=trait.value)
            )

    for lawbreak in model.lawbreaks:
        form.lawbreaks.append(
            UmbrealSheetLawbreakForm(id=lawbreak.id, name=lawbreak.name, description=lawbreak.description)
        )

    form.xp_1_milestone = model.xp_1_milestone
    form.xp_3_milestone = model.xp_3_milestone
    form.xp_10_milestone = model.xp_10_milestone
