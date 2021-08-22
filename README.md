# discord-modlinkbot

[![Discord Bot List](https://top.gg/api/widget/status/665861255051083806.svg)](https://top.gg/bot/665861255051083806)
[![Add to Discord server](https://img.shields.io/static/v1?style=flat&logo=discord&logoColor=FFF&label=&message=add%20to%20server&color=7289DA)](https://discordapp.com/oauth2/authorize?client_id=665861255051083806&permissions=19649&scope=bot)
[![License](https://img.shields.io/github/license/JonathanFeenstra/discord-modlinkbot)](https://github.com/JonathanFeenstra/discord-modlinkbot/blob/master/LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A [Discord](https://discord.com/) bot for linking [Nexus Mods](https://www.nexusmods.com/) search results.

## Features

Retrieve search results from [Nexus Mods](https://www.nexusmods.com/) for search queries in messages {between braces, separated by commas}, outside of any [Discord markdown](https://support.discord.com/hc/en-us/articles/210298617) or [spoiler tags](https://support.discord.com/hc/en-us/articles/360022320632), each query being between 3 and 100 characters in length. Queries cannot contain any of the following characters: `` \";:=*%$&_<>?`[]{} ``.

![example1](img/example1.png)
![example2](img/example2.png)

This functionality is based on [u/modlinkbot on Reddit](https://www.reddit.com/r/modlinkbotsub/comments/dlp7d1/bot_operation_and_information/) and the [Nexus Mods Discord Bot](https://github.com/Nexus-Mods/discord-bot/) quicksearch command. In addition, games to search for can be configured per server or channel by using commands.

Detailed descriptions of commands and their usage are provided by using the `.help` command.

## Self-hosting

### Configuration

[Make a Discord bot account](https://discordpy.readthedocs.io/en/latest/discord.html) and [enable the server members intent](https://discordpy.readthedocs.io/en/latest/intents.html#privileged-intents). If you wish, you can use the [included icon image](https://raw.githubusercontent.com/JonathanFeenstra/discord-modlinkbot/master/img/icon.png) for your bot. Create a `config.py` file in this directory and fill it in according to the [example](config.py.example). [Add the bot to a Discord server](https://discordpy.readthedocs.io/en/latest/discord.html#inviting-your-bot) to make use of its features.

### Local installation

The bot requires [Python 3.9](https://www.python.org/downloads/) and the libraries specified in [Pipfile](Pipfile), which can be installed using [`pipenv`](https://pipenv.pypa.io/en/stable/install/#installing-pipenv):

```sh
pipenv install
```

The following command will start modlinkbot:

```sh
pipenv run bot
```

### Docker

Alternatively, the bot can be deployed in a [Docker](https://www.docker.com/get-started) container:

```sh
docker-compose up
```
