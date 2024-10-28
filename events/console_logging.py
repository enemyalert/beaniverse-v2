import sys
import asyncio
import logging
from typing import Optional, TYPE_CHECKING
import discord
from discord.ext import commands

if TYPE_CHECKING:
    class ExtendedBot(commands.Bot):
        _discord_handler: 'DiscordHandler'
        _stderr_catcher: 'StderrCatcher'

class DiscordHandler(logging.Handler):
    def __init__(self, bot: commands.Bot, channel_id: int):
        super().__init__()
        self.bot = bot
        self.channel_id = channel_id
        self.queue: asyncio.Queue = asyncio.Queue()
        self.task: Optional[asyncio.Task] = None
        self.stopped = False

    def emit(self, record: logging.LogRecord):
        if self.stopped:
            return
            
        try:
            msg = self.format(record)
            # Split messages that are too long
            while len(msg) > 1990:  # Discord has a 2000 char limit
                split_msg = msg[:1990]
                msg = msg[1990:]
                asyncio.create_task(self._queue_message(f"```\n{split_msg}```"))
            
            if msg:
                asyncio.create_task(self._queue_message(f"```\n{msg}```"))
        except Exception:
            self.handleError(record)

    async def _queue_message(self, message: str):
        await self.queue.put(message)
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._process_queue())

    async def _process_queue(self):
        while not self.queue.empty():
            message = await self.queue.get()
            try:
                channel = self.bot.get_channel(self.channel_id)
                if channel and isinstance(channel, discord.TextChannel):
                    await channel.send(message)
                await asyncio.sleep(0.5)  # Rate limiting protection
            except Exception as e:
                print(f"Failed to send message to Discord: {e}", file=sys.stderr)
            finally:
                self.queue.task_done()

    def close(self):
        """Closes the handler cleanly"""
        self.stopped = True
        if self.task and not self.task.done():
            self.task.cancel()
        super().close()

class StderrCatcher:
    def __init__(self, handler: DiscordHandler):
        self.handler = handler
        self.original_stderr = sys.stderr
        self.logger = logging.getLogger('stderr')
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)

    def write(self, message: str):
        if message.strip():  # Only log non-empty messages
            self.logger.info(message.strip())
        self.original_stderr.write(message)

    def flush(self):
        self.original_stderr.flush()

def setup_console_logging(bot: commands.Bot, channel_id: int):
    """
    Sets up console logging to a Discord channel
    
    Args:
        bot: The Discord bot instance
        channel_id: The ID of the channel to log to
    """
    # Create and set up the Discord handler
    discord_handler = DiscordHandler(bot, channel_id)
    discord_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    )
    
    # Add handler to the root logger
    root_logger = logging.getLogger()
    root_logger.addHandler(discord_handler)
    
    # Redirect stderr
    stderr_catcher = StderrCatcher(discord_handler)
    sys.stderr = stderr_catcher

    # Store references to prevent garbage collection using setattr
    setattr(bot, '_discord_handler', discord_handler)
    setattr(bot, '_stderr_catcher', stderr_catcher)