# discord-modlinkbot
[![Discord Bots](https://top.gg/api/widget/status/665861255051083806.svg)](https://top.gg/bot/665861255051083806)
[![License](https://img.shields.io/github/license/JonathanFeenstra/discord-modlinkbot)](https://github.com/JonathanFeenstra/discord-modlinkbot/blob/master/LICENSE)

A [Discord](https://discord.com/) bot for linking [Nexus Mods](https://www.nexusmods.com/) search results.
## Features
Retrieve search results from [Nexus Mods](https://www.nexusmods.com/) for search queries in messages {between braces, separated by commas}, outside of any [Discord markdown](https://support.discord.com/hc/en-us/articles/210298617) or [spoiler tags](https://support.discord.com/hc/en-us/articles/360022320632), each query being between 3 and 120 characters in length. Queries cannot contain any of the following characters: ```\";:=*%$&_<>?`[]```.

![Example](img/example.png)

This functionality is based on [u/modlinkbot on Reddit](https://www.reddit.com/r/modlinkbotsub/comments/dlp7d1/bot_operation_and_information/) and the [Nexus Mods Discord Bot](https://github.com/Nexus-Mods/discord-bot/) quicksearch command. In addition, search filters are configurable per server and channel using commands.

Known bug: the [Nexus Mods search route](https://search.nexusmods.com/mods) returns outdated statistics which may lead to an incorrect first result (not the mod with the most endorsements).

Detailed descriptions of the available commands and their usage are sent by the bot when using the `.help` command.
## Self-hosting Installation
### Requirements
- [Python](https://www.python.org/downloads/) >= 3.8
- [aiohttp]() >= 3.6.2
- [aiosqlite](https://aiosqlite.omnilib.dev/en/stable/) >= 0.15.0
- [discord.py](https://github.com/Rapptz/discord.py) == 1.5.0

The required Python libraries can be installed with pip using the command:
```
pip install -r requirements.txt
```
### Configuration
Create a `config.py` file in the same directory as `bot.py`. [Make a Discord bot account](https://discordpy.readthedocs.io/en/latest/discord.html), [enable the server members intent](https://discordpy.readthedocs.io/en/latest/intents.html#privileged-intents) and add the bot token to `config.py` as follows:
```python3
token = 'your Discord bot token'
```
The following settings are optional:
```python3
# Set the webhook URL for logging when the bot is added or removed from a server
webhook_url = 'your webhook URL'

# Set a custom database path
db_path = 'modlinkbot.db'

# Add the Discord user IDs that may use owner-only commands
owner_ids = {
    340577388331139072,  # Jonathan (developer)
    255144776695808001,  # Yoosk (host)
}

# Set the maximum number of search result messages per search
max_result_embeds = 3

# Set the maximum number of servers that the bot can join
max_guilds = 1024
```
### Launch
Run `bot.py` to start modlinkbot. The bot will stay online as long as the script is running. [Add the bot to a Discord server](https://discordpy.readthedocs.io/en/latest/discord.html#inviting-your-bot) to make use of its features.
