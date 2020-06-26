# discord-modlinkbot
A Discord bot for linking game mods.

## Features
Retrieve search results from [Nexus Mods](https://www.nexusmods.com/) for search queries in messages {between braces, separated by commas}, outside of any [Discord markdown](https://support.discord.com/hc/en-us/articles/210298617) or [spoiler tags](https://support.discord.com/hc/en-us/articles/360022320632), each query being between 3 and 120 characters in length. Queries cannot contain any of the following characters: ```\";:=*%$&_<>?`[]```.

![Example](img/example.png)

This functionality is based on [u/modlinkbot on Reddit](https://www.reddit.com/r/modlinkbotsub/comments/dlp7d1/bot_operation_and_information/) and the [Nexus Mods Discord Bot](https://github.com/Nexus-Mods/discord-bot/) quicksearch command. In addition, search filters are configurable per server and channel using commands.

Detailed descriptions of the available commands and their usage are sent by the bot when using the `.help` command.
## Self-hosting Installation
### Requirements
- [Python](https://www.python.org/downloads/) >= 3.8
- [discord.py](https://github.com/Rapptz/discord.py) == 1.3.3

### Configuration
Create a `config.py` file in the same directory as `main.py`. [Make a Discord bot account](https://discordpy.readthedocs.io/en/latest/discord.html) and add the bot token to `config.py` as follows:
```python3
TOKEN = 'your Discord bot token'
```
Add the cogs (extensions) that will be loaded on initialisation:
```python3
INITIAL_COGS = (
    'cogs.admin',
    'cogs.db',
    'cogs.modsearch',
    'cogs.util',
)
```
Add the Discord user IDs that may use owner-only commands (optional):
```python3
OWNER_IDS = {
    340577388331139072,  # Jonathan (bot developer)
    255144776695808001,  # Yoosk (bot host)
}
```
Set the maximum number of guilds that the bot can join (optional):
```python3
MAX_GUILDS = 512
```
### Launch
Run `main.py` and [add the bot to the Discord server](https://discordpy.readthedocs.io/en/latest/discord.html#inviting-your-bot). The bot will only stay online as long as the script is running. Hosting can for example be done on cloud platforms such as [Heroku](https://www.heroku.com).
