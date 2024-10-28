import asyncio
import discord
from discord.ext import commands, tasks
import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from typing import List, Union
from pathlib import Path
from dotenv import load_dotenv

print(sys.executable) 
# Get absolute path to the project directory
BASE_DIR = Path(__file__).resolve().parent

# Load environment variables
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
        
        # Add these lines to fix attribute errors
        self._discord_handler = None
        self._stderr_catcher = None
        
        # Bot configuration
        self.status_switch = True
        self.activities: List[ActivityConfig] = [
            ActivityConfig("beans' agony"),
            ActivityConfig("{{guild_count}} servers!", discord.ActivityType.watching),
            ActivityConfig("Python 3.11", discord.ActivityType.playing),
            ActivityConfig("while migrating to discord.py 2.x", discord.ActivityType.listening)
        ]
        self.activity_index = 0
        
        # Get console channel ID from environment
        self.console_channel_id = int(os.getenv('CONSOLE_CHANNEL_ID', '0'))
        
        # Initialize logger
        self.setup_logging()

    def setup_logging(self):
        """Sets up the logging configuration"""
        try:
            # Create logs directory if it doesn't exist
            logs_dir = BASE_DIR / 'logs'
            logs_dir.mkdir(exist_ok=True)

            log_file = logs_dir / 'bot.log'
            max_log_size = 5 * 1024 * 1024  # 5 MB
            backup_count = 5

            # Create handlers
            file_handler = RotatingFileHandler(
                log_file, 
                maxBytes=max_log_size, 
                backupCount=backup_count,
                encoding='utf-8'
            )
            console_handler = logging.StreamHandler(sys.stdout)  # Changed to stdout

            # Create formatters
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            # Set up root logger
            logging.basicConfig(
                level=logging.INFO,
                handlers=[file_handler, console_handler]
            )

            self.logger = logging.getLogger('BotLogger')
            self.logger.info('Logging system initialized')
            
        except Exception as e:
            print(f"Failed to setup logging: {e}", file=sys.stderr)
            raise

    async def setup_hook(self):
        """Initialize the bot's extensions and settings"""
        try:
            # Setup console redirection if needed
            if self.console_channel_id:
                # Import here to avoid circular imports
                from events.console_logging import setup_console_logging
                setup_console_logging(self, self.console_channel_id)
                self.logger.info("Console logging setup completed")

            # Load all cogs
            await self.load_cogs()
            
            # Sync application commands
            await self.tree.sync()
            self.logger.info("Application commands synced")
            
        except Exception as e:
            self.logger.error(f"Error in setup_hook: {e}", exc_info=True)
            raise

    async def load_cogs(self):
        """Load all cogs from the cogs directory"""
        try:
            # Get absolute path to cogs directory
            cogs_dir = BASE_DIR / 'cogs'
            
            self.logger.info(f'Looking for cogs in: {cogs_dir}')
            
            if not cogs_dir.exists():
                self.logger.error(f'Cogs directory not found at: {cogs_dir}')
                raise FileNotFoundError(f'Cogs directory not found at: {cogs_dir}')
            
            cog_count = 0
            for file in cogs_dir.glob('*.py'):
                if file.name != '__init__.py':
                    try:
                        await self.load_extension(f'cogs.{file.stem}')
                        self.logger.info(f'Loaded cog: {file.stem}')
                        cog_count += 1
                    except Exception as e:
                        self.logger.error(f'Failed to load cog {file.stem}: {str(e)}')
            
            self.logger.info(f'Successfully loaded {cog_count} cogs')
            
        except Exception as e:
            self.logger.error(f"Error loading cogs: {e}", exc_info=True)
            raise

    async def on_ready(self):
        """Called when the bot is ready"""
        if self.user is None:  # Add null check
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
        
        # Start status rotation
        if not self.change_status.is_running():
            self.change_status.start()

    @tasks.loop(seconds=3)
    async def change_status(self):
        """Rotate bot's status and activity"""
        try:
            # Get current activity configuration
            activity_config = self.activities[self.activity_index]
            
            # Create activity with current guild count
            activity = activity_config.create_activity(len(self.guilds))
            
            # Update presence
            await self.change_presence(
                activity=activity,
                status=discord.Status.dnd if self.status_switch else discord.Status.idle
            )
            
            # Update states
            self.status_switch = not self.status_switch
            if self.status_switch:
                self.activity_index = (self.activity_index + 1) % len(self.activities)
                
        except Exception as e:
            self.logger.error(f"Error in change_status: {e}")

    @change_status.before_loop
    async def before_change_status(self):
        """Ensure the bot is ready before starting the status loop"""
        await self.wait_until_ready()

    async def on_error(self, event_method: str, *args, **kwargs):
        """Global error handler for events"""
        self.logger.error(f'Error in {event_method}:', exc_info=sys.exc_info())

    async def close(self):
        """Clean up resources before shutting down"""
        self.logger.info("Bot is shutting down...")
        
        # Stop status update task
        if self.change_status.is_running():
            self.change_status.cancel()
        
        # Perform cleanup
        try:
            if self._discord_handler:
                self._discord_handler.close()
            
            # Restore original stderr if it was modified
            if self._stderr_catcher:
                sys.stderr = self._stderr_catcher.original_stderr
                
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
        
        # Call parent's close method
        await super().close()

async def main():
    """Main entry point for the bot"""
    # Get token from environment
    TOKEN = os.getenv('TOKEN')
    if not TOKEN:
        raise ValueError("No token found in environment variables!")
    
    # Create and run bot
    bot = Bot()
    
    try:
        async with bot:
            await bot.start(TOKEN)
    except KeyboardInterrupt:
        # Handle graceful shutdown on Ctrl+C
        await bot.close()
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        await bot.close()
        sys.exit(1)

if __name__ == "__main__":
    # Run the bot
    asyncio.run(main())
