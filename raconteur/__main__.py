import logging.config
from argparse import ArgumentParser

from raconteur.config import config
from raconteur.db import setup_db

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "root": {"level": "INFO", "handlers": ["console"]},
    "loggers": {
        "gunicorn": {"level": "INFO", "propagate": False, "handlers": ["console"]},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "default",
        }
    },
    "formatters": {
        "default": {
            "format": "[%(asctime)s] %(levelname)s - %(name)s:%(lineno)s - %(message)s"
        },
    },
}

logging.config.dictConfig(LOGGING_CONFIG)


def run_bot() -> None:
    from discord import VoiceClient
    from raconteur.bot import RaconteurBot

    # Ensure the database's tables are fully set up
    setup_db()

    VoiceClient.warn_nacl = False
    bot = RaconteurBot()
    bot.run(config.bot_token)


def run_website() -> None:
    import uvicorn

    # Ensure the database's tables are fully set up
    setup_db()

    uvicorn.run(
        "raconteur.web.app:app",
        host="0.0.0.0",
        port=config.web_port,
        debug=config.web_debug,
        workers=1,
        log_config=LOGGING_CONFIG,
        root_path=config.web_root_path,
    )


if __name__ == "__main__":
    arg_parser = ArgumentParser()
    arg_parser.add_argument("component")
    args = arg_parser.parse_args()
    if args.component == "bot":
        run_bot()
    elif args.component == "web":
        run_website()
    else:
        raise ValueError(f'Invalid component "{args.component}", must be one of: "bot", "web"')
