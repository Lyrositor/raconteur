from discord import Guild
from sqlalchemy.orm import Session

from raconteur.models.game import Game, GamePlugin


def get_or_create_game(session: Session, guild: Guild) -> Game:
    game = session.get(Game, guild.id)
    if not game:
        # Ensure there is always a game instance containing at least the core plugin
        game = Game(guild_id=guild.id, name=guild.name)
        game.plugins.append(GamePlugin(name="CorePlugin"))
        session.add(game)
        session.commit()
    return game
