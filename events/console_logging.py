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
        
        self.level_colors = {
            logging.DEBUG: 0x808080,    # Gray
            logging.INFO: 0x00FF00,     # Green
            logging.WARNING: 0xFFA500,  # Orange
            logging.ERROR: 0xFF0000,    # Red
            logging.CRITICAL: 0x8B0000  # Dark Red
        }

    def emit(self, record: logging.LogRecord):
        if self.stopped:
            return
            
        try:
            msg = self.format(record)
            color = self.level_colors.get(record.levelno, 0xFFFFFF)  # Default to white
            
            while len(msg) > 1990:  
                split_msg = msg[:1990]
                msg = msg[1990:]
                asyncio.create_task(self._queue_message(split_msg, color))
            
            if msg:
                asyncio.create_task(self._queue_message(msg, color))
        except Exception:
            self.handleError(record)

    async def _queue_message(self, message: str, color: int):
        await self.queue.put((message, color))
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._process_queue())

    async def _process_queue(self):
        while not self.queue.empty():
            message, color = await self.queue.get()
            try:
                channel = self.bot.get_channel(self.channel_id)
                if channel and isinstance(channel, discord.TextChannel):
                    embed = discord.Embed(
                        description=f"```\n{message}```",
                        color=color
                    )
                    await channel.send(embed=embed)
                await asyncio.sleep(0.5) 
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
        if message.strip():  
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

    discord_handler = DiscordHandler(bot, channel_id)
    discord_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    )
    
    root_logger = logging.getLogger()
    root_logger.addHandler(discord_handler)
    
    stderr_catcher = StderrCatcher(discord_handler)
    sys.stderr = stderr_catcher

    setattr(bot, '_discord_handler', discord_handler)
    setattr(bot, '_stderr_catcher', stderr_catcher)
