from pydantic import BaseSettings


class Config(BaseSettings):
    db_uri: str = "sqlite:///raconteur.db"

    bot_token: str
    bot_client_id: str
    bot_client_secret: str

    web_debug: bool = False
    web_port: int = 6897
    web_session_secret: str = "please_change_me"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


config = Config()
