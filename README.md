.# beaniverse-v2
Beans s2s discord bot. [Add Beaniverse on your server!](https://discord.com/oauth2/authorize?client_id=992874324996399196&scope=bot&permissions=8)

To locally run this bot:
- install python 3.12.6
- install virtual environment
- install `pip install requirements.txt` on your shell
- add `.env` file
```
TOKEN= // Your discord token
MONGODB_URI= // create a mongo database. https://www.mongodb.com.
CONSOLE_CHANNEL_ID= // channel id logs
AUTHORIZED_USERS= // user id
```
- tweak the channels ids in some files there
- run `python main.py`
- After running the bot, `blacklist.txt` will appear. You can optionally insert your desired blacklisted word/s. Then rerun the program.
