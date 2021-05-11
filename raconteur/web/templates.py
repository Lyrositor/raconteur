from typing import Any

# noinspection PyProtectedMember
from starlette.templating import Jinja2Templates, _TemplateResponse

from raconteur.web.context import RequestContext

templates = Jinja2Templates(directory="templates")


def render_response(name: str, context: RequestContext, **kwargs: Any) -> _TemplateResponse:
    # Build the menu based on which plugins are active for this game
    from raconteur.plugins import PLUGINS
    menu = {}
    if context.current_game:
        for plugin in PLUGINS:
            for label, route_or_sub_menu in plugin.get_web_menu_for_game(context.current_game).items():
                if isinstance(route_or_sub_menu, dict):
                    if label not in menu:
                        menu[label] = {}
                    for sub_label, sub_route in route_or_sub_menu.items():
                        menu[label][sub_label] = context.request.url_for(
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
        entry = {"id": f"{id_prefix}{i}", "label": label, "route": None, "children": []}
        if isinstance(route_or_sub_menu, dict):
            entry["children"] = _prepare_menu(route_or_sub_menu, f"{i}-")
        else:
            entry["route"] = route_or_sub_menu
        sorted_menu.append(entry)
    return sorted_menu
