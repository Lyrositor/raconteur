Raconteur
=========

*A Discord bot for running complex online roleplays.*

**License:** Creative Commons CC0 1.0 Universal

## Using

The easiest way to use Raconteur is to invite the running instance to your server.

**Production:** *Not available yet*

**Development:** [Invite Link](https://discord.com/api/oauth2/authorize?client_id=838168138432380978&permissions=2617764977&scope=bot)

## Developing

You will need [Python 3.9+](https://www.python.org/) and [Poetry](https://python-poetry.org/) to set up your development environment.

1. Install Python 3.9+
2. Install Poetry by following its [installation guide](https://python-poetry.org/docs/#installation)
3. Run `poetry init`. 
   * This should create a virtual environment for your installation of Raconteur; make sure it's activated whenever running Raconteur.
4. Copy `example.env` to `.env` and fill in your details. You will need to create an application through the [Discord developer portal](https://discord.com/developers/applications) and use its provided settings.
5. You're good to go, you can now start the bot.
   * `raconteur\__main__.py bot` to start the Discord bot
   * `raconteur\__main__.py web` to start the website
