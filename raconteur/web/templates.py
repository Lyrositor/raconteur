from html import escape
from typing import Any, Union

# noinspection PyProtectedMember
from jinja2 import contextfilter
from markupsafe import Markup
from starlette.templating import Jinja2Templates, _TemplateResponse

from raconteur.web.context import RequestContext

TemplateResponse = _TemplateResponse

templates = Jinja2Templates(directory="templates")


EMOJIS = {
    "d4": "images/umbreal/d4.png",
    "d6": "images/umbreal/d6.png",
    "d8": "images/umbreal/d8.png",
    "d10": "images/umbreal/d10.png",
    "d12": "images/umbreal/d12.png",
    "PP": "images/umbreal/PP.png",
}


@contextfilter
def emojis(context: dict[str, Any], value: str) -> Markup:
    value = escape(value)
    for name, image in EMOJIS.items():
        path = context["url_for"](context, "static", path=image)
        value = value.replace(f":{name}:", f'<img src="{path}" class="emoji" width=22 height=22 />')
    return Markup(value)


templates.env.filters["emojis"] = emojis


def render_response(name: str, context: RequestContext, **kwargs: Any) -> TemplateResponse:
    # Build the menu based on which plugins are active for this game
    from raconteur.plugins import PLUGINS
    menu: dict[str, Union[str, dict[str, str]]] = {}
    if context.current_game and context.permissions.is_member:
        for plugin in PLUGINS:
            for label, route_or_sub_menu in plugin.get_web_menu_for_game(context.current_game).items():
                if isinstance(route_or_sub_menu, dict):
                    if label not in menu:
                        menu[label] = {}
                    for sub_label, sub_route in route_or_sub_menu.items():
                        menu[label][sub_label] = context.request.url_for(  # type: ignore
                            sub_route, current_game_id=context.current_game.guild_id
                        )
                elif isinstance(route_or_sub_menu, str):
                    menu[label] = context.request.url_for(
                        route_or_sub_menu, current_game_id=context.current_game.guild_id
                    )
                else:
                    raise TypeError(f"Invalid entry type for menu: {route_or_sub_menu}")

    return templates.TemplateResponse(
        name=name,
        context=dict(menu=_prepare_menu(menu), **context.to_dict(), **kwargs)
    )


def _prepare_menu(menu: dict[str, Any], id_prefix: str = "") -> list[dict[str, Any]]:
    sorted_menu = []
    for i, (label, route_or_sub_menu) in enumerate(sorted(menu.items())):
        entry: dict[str, Any] = {"id": f"{id_prefix}{i}", "label": label, "route": None, "children": []}
        if isinstance(route_or_sub_menu, dict):
            entry["children"] = _prepare_menu(route_or_sub_menu, f"{i}-")
        else:
            entry["route"] = route_or_sub_menu
        sorted_menu.append(entry)
    return sorted_menu
