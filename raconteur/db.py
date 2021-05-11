from raconteur.models.base import Base, engine
from raconteur.plugins import PLUGINS


def setup_db():
    # Ensure all the DB models are created
    for plugin_cls in PLUGINS:
        plugin_cls.assert_models()

    Base.metadata.create_all(engine)
