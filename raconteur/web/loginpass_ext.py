# Taken from: https://github.com/authlib/loginpass/blob/master/loginpass/_fastapi.py
# The latest published version of loginpass as of this writing (0.5) does not have FastAPI support yet
from collections import Callable
from typing import Any, Type

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException
from loginpass import Discord
from starlette.requests import Request
from starlette.responses import Response


def create_fastapi_routes(backends: list[Any], oauth: OAuth, handle_authorize: Callable) -> APIRouter:
    """Create a Fastapi routes that you can register it directly to fastapi
    app. The routes contains two route: ``/auth/<backend>`` and
    ``/login/<backend>``::

        from authlib.integrations.starlette_client import OAuth
        from fastapi.responses import HTMLResponse
        from starlette.config import Config
        from starlette.middleware.sessions import SessionMiddleware
        from loginpass import create_fastapi_routes, Twitter, GitHub, Google

        from fastapi import FastAPI

        app = FastAPI()
        config = Config(".env")
        oauth = OAuth(config)

        app.add_middleware(SessionMiddleware, secret_key=config.get("SECRET_KEY"))

        async def handle_authorize(remote, token, user_info, request):
            return user_info

        router = create_fastapi_routes([GitHub, Google], oauth, handle_authorize)
        app.include_router(router, prefix="/account")

        # visit /account/login/github
        # callback /account/auth/github

    :param backends: A list of configured backends
    :param oauth: Authlib Flask OAuth instance
    :param handle_authorize: A function to handle authorized response
    :return: Fastapi APIRouter instance
    """
    router = APIRouter()

    for b in backends:
        register_to(oauth, b)

    @router.get("/auth/{backend}")
    async def auth(
        backend: str,
        id_token: str = None,
        code: str = None,
        oauth_verifier: str = None,
        request: Request = None,
    ) -> Response:
        remote = oauth.create_client(backend)
        if remote is None:
            raise HTTPException(404)

        if code:
            token = await remote.authorize_access_token(request)
            if id_token:
                token["id_token"] = id_token
        elif id_token:
            token = {"id_token": id_token}
        elif oauth_verifier:
            # OAuth 1
            token = await remote.authorize_access_token(request)
        else:
            # handle failed
            return await handle_authorize(remote, None, None)
        if "id_token" in token:
            user_info = await remote.parse_id_token(request, token)
        else:
            remote.token = token
            user_info = await remote.userinfo(token=token)
        return await handle_authorize(remote, token, user_info, request)

    @router.get("/login/{backend}")
    async def login(backend: str, request: Request) -> Response:
        remote = oauth.create_client(backend)
        if remote is None:
            raise HTTPException(404)

        redirect_uri = request.url_for("auth", backend=backend)
        conf_key = "{}_AUTHORIZE_PARAMS".format(backend.upper())
        params = oauth.config.get(conf_key, default={})
        return await remote.authorize_redirect(request, redirect_uri, **params)

    return router


def register_to(oauth: OAuth, backend_cls: Type[Discord]) -> None:
    from authlib.integrations.starlette_client import StarletteRemoteApp

    class RemoteApp(backend_cls, StarletteRemoteApp):  # type: ignore
        OAUTH_APP_CONFIG = backend_cls.OAUTH_CONFIG

    oauth.register(RemoteApp.NAME, overwrite=True, client_cls=RemoteApp)
