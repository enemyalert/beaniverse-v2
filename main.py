import asyncio
import discord
import logging
import os
import sys
from discord.ext import commands, tasks
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List, Union
from dotenv import load_dotenv
from events.cogs import CogManager

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

class ActivityConfig:
    def __init__(self, text: str, type: discord.ActivityType = discord.ActivityType.playing):
        self.text = text
        self.type = type

    def create_activity(self, guild_count: int) -> Union[discord.Activity, discord.Game]:
        text = self.text.replace("{{guild_count}}", str(guild_count))
        if self.type == discord.ActivityType.playing:
            return discord.Game(name=text)
        return discord.Activity(type=self.type, name=text)

class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(
            command_prefix="!",
            intents=intents,
            status=discord.Status.dnd
        )
        
        self._discord_handler = None
        self._stderr_catcher = None
        
        self.status_switch = True
        self.activities: List[ActivityConfig] = [
            ActivityConfig("beans' agony"),
            ActivityConfig("{{guild_count}} servers!", discord.ActivityType.watching),
            ActivityConfig("Python 3.11", discord.ActivityType.playing),
            ActivityConfig("while migrating to discord.py 2.x", discord.ActivityType.listening)
        ]
        self.activity_index = 0
        
        self.console_channel_id = int(os.getenv('CONSOLE_CHANNEL_ID', '0'))
        
        self.setup_logging()
        self.cog_manager = CogManager(self)

    def setup_logging(self):
        logs_dir = BASE_DIR / 'logs'
        logs_dir.mkdir(exist_ok=True)

        log_file = logs_dir / 'bot.log'
        max_lines = 200
        backup_count = 1

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_lines * 512,
            backupCount=backup_count,
            encoding='utf-8'
        )
        console_handler = logging.StreamHandler(sys.stdout)

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        logging.basicConfig(
            level=logging.INFO,
            handlers=[file_handler, console_handler]
        )

        self.logger = logging.getLogger('Beaniverse-v2')
        self.logger.info('Logging system initialized')

    async def setup_hook(self):
        try:
            if self.console_channel_id:
                from events.console_logging import setup_console_logging
                setup_console_logging(self, self.console_channel_id)
                self.logger.info("Console logging setup completed")

            await self.cog_manager.load_cogs()
            await self.tree.sync()
            self.logger.info("Application commands synced")
            
        except Exception as e:
            self.logger.error(f"Error in setup_hook: {e}", exc_info=True)
            raise

    async def on_ready(self):
        if self.user is None:
            self.logger.error("Bot user is None")
            return
            
        self.logger.info(f'Logged in as {self.user} (ID: {self.user.id})')
        self.logger.info(f'Connected to {len(self.guilds)} guilds')
        
        if self.console_channel_id:
            try:
                channel = self.get_channel(self.console_channel_id)
                if channel and isinstance(channel, discord.TextChannel):
                    await channel.send("```\nBot is now online and console logging has started!```")
            except Exception as e:
                self.logger.error(f"Failed to send startup message: {e}")
        
        if not self.change_status.is_running():
            self.change_status.start()

    @tasks.loop(seconds=3)
    async def change_status(self):
        try:
            activity_config = self.activities[self.activity_index]
            activity = activity_config.create_activity(len(self.guilds))
            
            await self.change_presence(
                activity=activity,
                status=discord.Status.dnd if self.status_switch else discord.Status.idle
            )
            
            self.status_switch = not self.status_switch
            if self.status_switch:
                self.activity_index = (self.activity_index + 1) % len(self.activities)
                
        except Exception as e:
            self.logger.error(f"Error in change_status: {e}")

    @change_status.before_loop
    async def before_change_status(self):
        await self.wait_until_ready()

    async def on_error(self, event_method: str, *args, **kwargs):
        self.logger.error(f'Error in {event_method}:', exc_info=sys.exc_info())

    async def close(self):
        self.logger.info("Bot is shutting down...")
        
        if self.change_status.is_running():
            self.change_status.cancel()
        
        try:
            if self._discord_handler:
                self._discord_handler.close()
            
            if self._stderr_catcher:
                sys.stderr = self._stderr_catcher.original_stderr
                
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
        
        await super().close()

async def main():
    TOKEN = os.getenv('TOKEN')
    if not TOKEN:
        raise ValueError("No token found in environment variables!")
    
    bot = Bot()
    
    try:
        async with bot:
            await bot.start(TOKEN)
    except KeyboardInterrupt:
        await bot.close()
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        await bot.close()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
