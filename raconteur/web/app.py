from fastapi import FastAPI, APIRouter
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.staticfiles import StaticFiles

from raconteur.config import config
from raconteur.models.base import get_session
from raconteur.plugins import PLUGINS
from raconteur.web.auth import get_auth_router
from raconteur.web.context import RequestContext
from raconteur.web.templates import render_response

base_router = APIRouter()


@base_router.get("/")
async def home(request: Request):
    with get_session() as session:
        return render_response("home.html", await RequestContext.build(session, request, None))


@base_router.get("/{current_game_id}")
async def home_with_game(request: Request, current_game_id: int):
    with get_session() as session:
        return render_response("home.html", await RequestContext.build(session, request, current_game_id))


def setup_app():
    _app = FastAPI(
        title="Raconteur", openapi_url=None, docs_url=None, redoc_url=None, swagger_ui_oauth2_redirect_url=None
    )
    _app.add_middleware(SessionMiddleware, secret_key=config.web_session_secret)

    _app.include_router(get_auth_router())
    _app.mount("/static", StaticFiles(directory="static"), name="static")
    for plugin in PLUGINS:
        if router := plugin.get_web_router():
            _app.include_router(router)
    _app.include_router(base_router)

    return _app


app = setup_app()
