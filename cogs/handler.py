# handler.py

import discord
from discord.ext import commands
from pymongo import MongoClient
import os
from typing import Optional, Dict, Set, Tuple, List, Union
import aiofiles
import asyncio
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
import logging
from logging.handlers import RotatingFileHandler
from discord import TextChannel

# Load environment variables
load_dotenv()

# Get the directory where the current script is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Define the log directory and ensure it exists
LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)  # Creates the directory if it doesn't exist

# Define the absolute path to the log file
# Optionally, you can set LOG_PATH via an environment variable
LOG_PATH = os.getenv('LOG_PATH', os.path.join(LOG_DIR, 'bot.log'))

# Configure rotating logging
try:
    rotating_handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=5*1024*1024,  # 5 MB
        backupCount=5,         # Keep up to 5 backup files
        encoding='utf-8'
    )
except Exception as e:
    # Fallback to a basic file handler if RotatingFileHandler fails
    print(f"Failed to initialize RotatingFileHandler: {e}")
    rotating_handler = logging.FileHandler(LOG_PATH, encoding='utf-8')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        rotating_handler,                # Rotating log file handler
        logging.StreamHandler()          # Also log to console
    ]
)

logger = logging.getLogger(__name__)

# Define the absolute path to blacklist.txt
BLACKLIST_PATH = os.path.join(BASE_DIR, 'blacklist.txt')


class MuteExpiredView(discord.ui.View):
    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = channel_id

        # Add the URL button directly in the constructor
        self.add_item(discord.ui.Button(
            label="Support Server",
            style=discord.ButtonStyle.secondary,
            url="https://discord.gg/HngQ9JDdmJ"
        ))

    @discord.ui.button(label="Go to Channel", style=discord.ButtonStyle.primary)
    async def go_to_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"Here's the channel: <#{self.channel_id}>", ephemeral=True)


class GlobalChatHandler(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # MongoDB setup
        mongodb_uri = os.getenv('MONGODB_URI')
        if not mongodb_uri:
            logger.error("MONGODB_URI not found in environment variables.")
            raise ValueError("MONGODB_URI not found in environment variables")

        # Configuration
        self.SPAM_COOLDOWN = 2  # seconds (more lenient)
        self.SPAM_THRESHOLD = 8  # messages
        self.SPAM_TIME_WINDOW = 1  # second
        self.BLACKLIST_COOLDOWN = 60  # seconds
        self.MAX_MESSAGE_LENGTH = 2000  # Discord's limit
        self.MAX_ATTACHMENTS = 10
        self.MUTE_CHECK_INTERVAL = 5  # seconds
        self.WEBHOOK_NAME = 'beaniverse'

        try:
            self.client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
            # The following line attempts to fetch server info to validate the connection
            self.client.server_info()
            self.db = self.client['global_chat']
            self.servers = self.db['servers']
            self.users = self.db['users']
            self.message_logs = self.db['message_logs']
            logger.info("Connected to MongoDB successfully.")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise

        # Cache structures
        self.webhooks: Dict[int, discord.Webhook] = {}
        self.user_message_count: Dict[int, List[float]] = {}
        self.muted_users: Dict[int, Tuple[datetime, str, Optional[discord.Message], int]] = {}
        self.blacklisted_words: Set[str] = set()
        self.registered_channels: Set[int] = set()

        # Set up MongoDB indexes
        self.setup_indexes()

        # Start background tasks
        self.bot.loop.create_task(self._load_blacklist())
        self.bot.loop.create_task(self.load_registered_channels())
        self.monitor_task = self.bot.loop.create_task(self.monitor_mutes())

    def setup_indexes(self) -> None:
        """Set up MongoDB indexes for better query performance."""
        try:
            self.users.create_index([("user_id", 1)], unique=True)
            self.servers.create_index([("channel_id", 1)], unique=True)
            self.message_logs.create_index([("timestamp", 1)])
            self.message_logs.create_index([("user_id", 1)])
            logger.info("MongoDB indexes created successfully!")
        except Exception as e:
            logger.error(f"Error creating MongoDB indexes: {e}")

    async def _load_blacklist(self) -> None:
        """Load blacklisted words from a file."""
        try:
            async with aiofiles.open(BLACKLIST_PATH, mode='r', encoding='utf-8') as f:
                content = await f.read()
                self.blacklisted_words = set(
                    word.strip().lower()
                    for word in content.split('\n')
                    if word.strip() and not word.startswith('#')
                )
            logger.info(f"Loaded {len(self.blacklisted_words)} blacklisted words.")
        except FileNotFoundError:
            logger.warning("blacklist.txt not found. Creating an empty file.")
            try:
                async with aiofiles.open(BLACKLIST_PATH, mode='w', encoding='utf-8') as f:
                    await f.write("# Add blacklisted words here, one per line\n")
                self.blacklisted_words = set()
                logger.info("Created empty blacklist.txt.")
            except PermissionError as pe:
                logger.error(f"Permission denied while creating blacklist.txt: {pe}")
                self.blacklisted_words = set()
            except Exception as e:
                logger.error(f"Error creating blacklist.txt: {e}")
                self.blacklisted_words = set()
        except PermissionError as pe:
            logger.error(f"Permission denied while accessing blacklist.txt: {pe}")
            self.blacklisted_words = set()
        except Exception as e:
            logger.error(f"Error loading blacklist: {e}")
            self.blacklisted_words = set()

    async def load_registered_channels(self) -> None:
        """Load registered channels into cache."""
        try:
            servers = self.servers.find({}, {'channel_id': 1})
            self.registered_channels = {int(server['channel_id']) for server in servers if 'channel_id' in server}
            logger.info(f"Loaded {len(self.registered_channels)} registered channels.")
        except Exception as e:
            logger.error(f"Error loading registered channels: {e}")
            self.registered_channels = set()

    def is_channel_registered(self, channel_id: int) -> bool:
        """Check if a channel is registered for global chat."""
        return channel_id in self.registered_channels

    def contains_blacklisted_words(self, content: str) -> bool:
        """Check if message contains blacklisted words."""
        return any(word in content.lower() for word in self.blacklisted_words)

    def is_user_muted(self, user_id: int) -> Tuple[bool, Optional[str], Optional[discord.Message], Optional[int]]:
        """Check if a user is muted and return status, reason, mute message, and channel_id."""
        if user_id in self.muted_users:
            mute_end_time, reason, mute_message, channel_id = self.muted_users[user_id]
            if datetime.utcnow() < mute_end_time:
                return True, reason, mute_message, channel_id
            else:
                del self.muted_users[user_id]
        return False, None, None, None

    async def get_or_create_webhook(self, channel: TextChannel) -> Optional[discord.Webhook]:
        """Get or create a webhook for the channel."""
        try:
            if channel.id in self.webhooks:
                return self.webhooks[channel.id]

            webhooks = await channel.webhooks()
            webhook = discord.utils.get(webhooks, name=self.WEBHOOK_NAME)

            if webhook is None:
                webhook = await channel.create_webhook(name=self.WEBHOOK_NAME)
                logger.info(f"Created new webhook for channel {channel.id}.")

            self.webhooks[channel.id] = webhook
            return webhook
        except discord.Forbidden:
            logger.error(f"Missing permissions to manage webhooks in channel {channel.id}.")
            return None
        except Exception as e:
            logger.error(f"Error getting or creating webhook in channel {channel.id}: {e}")
            return None

    async def mute_user(self, user: Union[discord.User, discord.Member], duration: int, reason: str, channel: TextChannel) -> None:
        """Mute a user and log the action."""
        end_time = datetime.utcnow() + timedelta(seconds=duration)

        try:
            self.users.update_one(
                {'user_id': user.id},
                {
                    '$push': {
                        'mute_history': {
                            'timestamp': datetime.utcnow(),
                            'duration': duration,
                            'reason': reason
                        }
                    }
                },
                upsert=True
            )
            logger.info(f"Logged mute action for user {user.id}.")
        except Exception as e:
            logger.error(f"Failed to log mute action for user {user.id}: {e}")

        embed = discord.Embed(
            title="You have been muted",
            description=f"Reason: {reason}",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(
            name="Duration",
            value=f"Until {discord.utils.format_dt(end_time, style='R')}"
        )

        is_muted, _, existing_mute_message, _ = self.is_user_muted(user.id)
        if is_muted and existing_mute_message:
            try:
                await existing_mute_message.edit(embed=embed)
                mute_message = existing_mute_message
                logger.info(f"Updated existing mute message for user {user.id}.")
            except discord.NotFound:
                try:
                    mute_message = await user.send(embed=embed)
                    logger.info(f"Sent new mute message to user {user.id}.")
                except discord.Forbidden:
                    logger.error(f"Cannot send messages to user {user.id}.")
                    mute_message = None
                except Exception as e:
                    logger.error(f"Error sending mute message to user {user.id}: {e}")
                    mute_message = None
            except discord.Forbidden:
                logger.error(f"Cannot send messages to user {user.id}.")
                mute_message = None
            except Exception as e:
                logger.error(f"Error updating/sending mute message for user {user.id}: {e}")
                mute_message = None
        else:
            try:
                mute_message = await user.send(embed=embed)
                logger.info(f"Sent mute message to user {user.id}.")
            except discord.Forbidden:
                logger.error(f"Failed to send mute notification to {user}.")
                mute_message = None
            except Exception as e:
                logger.error(f"Error sending mute message to user {user.id}: {e}")
                mute_message = None

        self.muted_users[user.id] = (end_time, reason, mute_message, channel.id)

        # Send a message in the channel
        try:
            await channel.send(f"{user.mention}, you are currently muted. Wait for the cooldown.", delete_after=5)
            logger.info(f"Sent mute notification in channel {channel.id} for user {user.id}.")
        except Exception as e:
            logger.error(f"Failed to send mute notification in channel {channel.id}: {e}")

    async def monitor_mutes(self) -> None:
        """Monitor and handle expired mutes."""
        while not self.bot.is_closed():
            current_time = datetime.utcnow()
            expired_mutes = [
                user_id
                for user_id, (end_time, _, _, _) in self.muted_users.items()
                if current_time >= end_time
            ]

            for user_id in expired_mutes:
                _, _, mute_message, channel_id = self.muted_users.pop(user_id)
                user = self.bot.get_user(user_id)
                if user:
                    try:
                        embed = discord.Embed(
                            title="Mute Expired",
                            description="You can now send messages again.",
                            color=discord.Color.green(),
                            timestamp=current_time
                        )
                        view = MuteExpiredView(channel_id)
                        await user.send(embed=embed, view=view)
                        logger.info(f"Sent mute expired notification to user {user_id}.")

                        if mute_message:
                            try:
                                await mute_message.delete()
                                logger.info(f"Deleted mute message for user {user_id}.")
                            except Exception as e:
                                logger.error(f"Failed to delete mute message for user {user_id}: {e}")
                    except discord.Forbidden:
                        logger.warning(f"Failed to send mute expired notification to user {user_id}.")
                    except Exception as e:
                        logger.error(f"Error handling mute expiration for user {user_id}: {e}")

            await asyncio.sleep(self.MUTE_CHECK_INTERVAL)

    async def validate_message(self, message: discord.Message) -> Tuple[bool, Optional[str]]:
        """Validate message content and return (is_valid, error_reason)."""
        # First check if the channel is registered
        if not self.is_channel_registered(message.channel.id):
            return False, None  # Silent fail for unregistered channels

        # Check if the user is muted
        is_muted, reason, _, _ = self.is_user_muted(message.author.id)
        if is_muted:
            return False, reason

        if len(message.content) > self.MAX_MESSAGE_LENGTH:
            return False, "Message exceeds maximum length"

        if len(message.attachments) > self.MAX_ATTACHMENTS:
            return False, "Too many attachments"

        if self.contains_blacklisted_words(message.content):
            return False, "Message contains prohibited words"

        # Spam check
        user_id = message.author.id
        current_time = time.time()

        if user_id not in self.user_message_count:
            self.user_message_count[user_id] = []

        self.user_message_count[user_id].append(current_time)
        self.user_message_count[user_id] = [
            t for t in self.user_message_count[user_id]
            if current_time - t <= self.SPAM_TIME_WINDOW
        ]

        if len(self.user_message_count[user_id]) > self.SPAM_THRESHOLD:
            return False, "Too many messages sent in a short time"

        if len(self.user_message_count[user_id]) > 1:
            time_diff = current_time - self.user_message_count[user_id][-2]
            if time_diff < self.SPAM_COOLDOWN:
                return False, "Message sent too quickly"

        return True, None

    async def forward_message(self, message: discord.Message) -> None:
        """Forward message to all registered channels with enhanced error handling."""
        if message.author.bot:
            return

        # Check if source channel is registered
        if not self.is_channel_registered(message.channel.id):
            return

        # Validate message
        is_valid, error_reason = await self.validate_message(message)
        if not is_valid:
            if error_reason:  # Only act if there's an error reason (not for unregistered channels)
                cooldown_duration = self.SPAM_COOLDOWN if "quickly" in error_reason else self.BLACKLIST_COOLDOWN

                if isinstance(message.channel, TextChannel):
                    await self.mute_user(
                        message.author,
                        cooldown_duration,
                        error_reason,
                        message.channel
                    )
                else:
                    logger.warning(f"Attempted to mute user in a non-TextChannel: {message.channel}")

                try:
                    await message.delete()
                    logger.info(f"Deleted invalid message from user {message.author.id} in channel {message.channel.id}.")
                except Exception as e:
                    logger.error(f"Failed to delete message from user {message.author.id}: {e}")
            return

        # Log message
        try:
            self.message_logs.insert_one({
                'user_id': message.author.id,
                'channel_id': message.channel.id,
                'content': message.content,
                'timestamp': datetime.utcnow(),
                'attachment_count': len(message.attachments)
            })
            logger.info(f"Logged message from user {message.author.id} in channel {message.channel.id}.")
        except Exception as e:
            logger.error(f"Failed to log message from user {message.author.id}: {e}")

        # Forward to other registered channels
        for target_channel_id in self.registered_channels:
            if target_channel_id == message.channel.id:
                continue

            channel = self.bot.get_channel(target_channel_id)
            if not channel:
                logger.warning(f"Target channel {target_channel_id} not found.")
                continue

            if not isinstance(channel, TextChannel):
                logger.warning(f"Target channel {target_channel_id} is not a TextChannel.")
                continue

            try:
                webhook = await self.get_or_create_webhook(channel)
                if webhook:
                    # Update the username to include the server name
                    server_name = message.guild.name if message.guild else "Direct Message"
                    username = f"{message.author.display_name} | {server_name}"

                    files = []
                    for attachment in message.attachments:
                        try:
                            file = await attachment.to_file()
                            if file:
                                files.append(file)
                        except Exception as e:
                            logger.error(f"Failed to process attachment from user {message.author.id}: {e}")

                    # Ensure files is always a list
                    if not files:
                        files = []

                    # Additional logging before sending
                    logger.debug(f"Preparing to send message to webhook in channel {target_channel_id} with {len(files)} files.")

                    await webhook.send(
                        username=username,
                        avatar_url=message.author.display_avatar.url,
                        content=message.content or "",
                        files=files,  # Pass empty list if no files
                        allowed_mentions=discord.AllowedMentions(
                            everyone=False,
                            roles=False,
                            users=True
                        )
                    )
                    logger.info(f"Forwarded message to channel {target_channel_id}.")
            except Exception as e:
                logger.error(f"Failed to forward message to channel {target_channel_id}: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Listen for new messages and process them."""
        await self.forward_message(message)

    async def cleanup(self) -> None:
        """Cleanup resources and connections."""
        self.monitor_task.cancel()
        try:
            await self.monitor_task
        except asyncio.CancelledError:
            logger.info("Monitor task cancelled successfully.")
        try:
            self.client.close()
            logger.info("MongoDB connection closed.")
        except Exception as e:
            logger.error(f"Error closing MongoDB connection: {e}")

    async def cog_unload(self) -> None:
        """Proper cleanup on cog unload."""
        await self.cleanup()
        logger.info("GlobalChatHandler cog unloaded.")


async def setup(bot: commands.Bot) -> None:
    """Add the cog to the bot."""
    await bot.add_cog(GlobalChatHandler(bot))
    logger.info("GlobalChatHandler cog added to the bot.")