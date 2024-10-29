# beaniverse-v2
Beans s2s discord bot. [Add Beaniverse on your server!](https://discord.com/oauth2/authorize?client_id=992874324996399196&scope=bot&permissions=8)

To locally run this bot:
- install python 3.12.6
- install virtual environment
- install `pip install requirements.txt` on your shell
- add `.env` file
```
TOKEN=                                   Your discord token
MONGODB_URI=                             Create a mongo database. https://www.mongodb.com.
CONSOLE_CHANNEL_ID=                      Channel id for logs
AUTHORIZED_USERS=                        User ids (who can access ban and unban command)
```
- tweak the channels ids in some files there
- run `python main.py`
- After running the bot, `blacklist.txt` will appear. You can optionally insert your desired blacklisted word/s. Then rerun the program.
