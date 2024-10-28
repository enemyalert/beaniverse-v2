import discord
from discord.ext import commands
from pymongo import MongoClient
import os
from typing import Optional, Dict, Set, Tuple, List, Union
import aiofiles
import asyncio
import time
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import logging
from logging.handlers import RotatingFileHandler
from discord import TextChannel
import re
from events.nsfw import NSFWDetector

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

LOG_PATH = os.getenv('LOG_PATH', os.path.join(LOG_DIR, 'bot.log'))

try:
    rotating_handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=5*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
except Exception as e:
    print(f"Failed to initialize RotatingFileHandler: {e}")
    rotating_handler = logging.FileHandler(LOG_PATH, encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        rotating_handler,
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

BLACKLIST_PATH = os.path.join(BASE_DIR, 'blacklist.txt')


class MuteExpiredView(discord.ui.View):
    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = channel_id

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

        mongodb_uri = os.getenv('MONGODB_URI')
        if not mongodb_uri:
            logger.error("MONGODB_URI not found in environment variables.")
            raise ValueError("MONGODB_URI not found in environment variables")

        self.SPAM_COOLDOWN = 2
        self.SPAM_THRESHOLD = 8
        self.SPAM_TIME_WINDOW = 1
        self.BLACKLIST_COOLDOWN = 60
        self.MAX_MESSAGE_LENGTH = 2000
        self.MAX_ATTACHMENTS = 10
        self.MUTE_CHECK_INTERVAL = 5
        self.WEBHOOK_NAME = 'beaniverse'

        self.DISCORD_INVITE_PATTERN = re.compile(
            r'(?:https?://)?(?:www\.)?((?:discord\.(?:gg|io|me|li|com)|discordapp\.com)/(?:invite/)?[a-zA-Z0-9-]+)',
            re.IGNORECASE
        )
        
        self.ADULT_CONTENT_PATTERN = re.compile(
            r'(?:https?://)?(?:www\.)?'
            r'(?:'
            r'(?:[a-zA-Z0-9\-]+\.)*(?:porn|pinayflix|jakol|hubad|iyot|kayat|kantot|xxx|sex|adult|nsfw|hentai|xvideos|pornhub|xnxx|xhamster|redtube|youporn)'
            r'(?:\.[a-zA-Z]{2,})\b'
            r'|'
            r'(?:only\.)?fans/|onlyfans\.com'
            r')',
            re.IGNORECASE
        )
        
        try:
            self.client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
            self.client.server_info()
            self.db = self.client['global_chat']
            self.servers = self.db['servers']
            self.users = self.db['users']
            self.message_logs = self.db['message_logs']
            logger.info("Connected to MongoDB successfully.")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise

        self.webhooks: Dict[int, discord.Webhook] = {}
        self.user_message_count: Dict[int, List[float]] = {}
        self.muted_users: Dict[int, Tuple[datetime, str, Optional[discord.Message], int]] = {}
        self.blacklisted_words: Set[str] = set()
        self.registered_channels: Set[int] = set()
        self.nsfw_detector = NSFWDetector()

        self.setup_indexes()

        self.bot.loop.create_task(self._load_blacklist())
        self.bot.loop.create_task(self.load_registered_channels())
        self.monitor_task = self.bot.loop.create_task(self.monitor_mutes())

        self.reports = self.db['reports']
        self.reports_counter = self.db['reports_counter']
        
        self.setup_report_indexes()

    def setup_indexes(self) -> None:
        try:
            self.users.create_index([("user_id", 1)], unique=True)
            self.servers.create_index([("channel_id", 1)], unique=True)
            self.message_logs.create_index([("timestamp", 1)])
            self.message_logs.create_index([("user_id", 1)])
            logger.info("MongoDB indexes created successfully!")
        except Exception as e:
            logger.error(f"Error creating MongoDB indexes: {e}")

    def setup_report_indexes(self) -> None:
        try:
            self.reports.create_index("report_number")
            self.reports.create_index("reported_user_id")
            self.reports.create_index("reporter_id")
            self.reports.create_index("timestamp")
            logger.info("Report system indexes created successfully!")
        except Exception as e:
            logger.error(f"Error creating report system indexes: {e}")

    async def _load_blacklist(self) -> None:
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
        try:
            servers = self.servers.find({}, {'channel_id': 1})
            self.registered_channels = {int(server['channel_id']) for server in servers if 'channel_id' in server}
            logger.info(f"Loaded {len(self.registered_channels)} registered channels.")
        except Exception as e:
            logger.error(f"Error loading registered channels: {e}")
            self.registered_channels = set()

    def is_channel_registered(self, channel_id: int) -> bool:
        return channel_id in self.registered_channels

    def contains_blacklisted_words(self, content: str) -> bool:
        return any(word in content.lower() for word in self.blacklisted_words)

    def is_user_muted(self, user_id: int) -> Tuple[bool, Optional[str], Optional[discord.Message], Optional[int]]:
        if user_id in self.muted_users:
            mute_end_time, reason, mute_message, channel_id = self.muted_users[user_id]
            if datetime.now(timezone.utc) < mute_end_time:
                return True, reason, mute_message, channel_id
            else:
                del self.muted_users[user_id]
        return False, None, None, None

    async def get_or_create_webhook(self, channel: TextChannel) -> Optional[discord.Webhook]:
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
        current_time = datetime.now(timezone.utc)
        end_time = current_time + timedelta(seconds=duration)
        formatted_time = discord.utils.format_dt(end_time, style='R')

        embed = discord.Embed(
            title="You have been muted",
            description=f"Reason: {reason}",
            color=discord.Color.red()
        )
        embed.add_field(
            name="Duration",
            value=f"until in {duration} seconds"
        )

        logger.info(
            f"Muted user {user.id} until {end_time.strftime('%Y-%m-%d %H:%M:%S')} "
            f"for reason: {reason}"
        )

        try:
            self.users.update_one(
                {'user_id': user.id},
                {
                    '$push': {
                        'mute_history': {
                            'timestamp': current_time,
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

        try:
            await channel.send(f"{user.mention}, you are currently muted. Wait for the cooldown.", delete_after=5)
            logger.info(f"Sent mute notification in channel {channel.id} for user {user.id}.")
        except Exception as e:
            logger.error(f"Failed to send mute notification in channel {channel.id}: {e}")

        async def unmute_task():
            await asyncio.sleep(duration)
            unmute_embed = discord.Embed(
                title="Mute Expired",
                description="You can now send messages again.",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            view = MuteExpiredView(channel.id)
            await user.send(embed=unmute_embed, view=view)
        
        self.bot.loop.create_task(unmute_task())

    async def monitor_mutes(self) -> None:
        while not self.bot.is_closed():
            current_time = datetime.now(timezone.utc)
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
        if not self.is_channel_registered(message.channel.id):
            return False, None

        is_muted, reason, _, _ = self.is_user_muted(message.author.id)
        if is_muted:
            return False, reason

        if self.DISCORD_INVITE_PATTERN.search(message.content):
            return False, "Discord invites are not allowed"

        if self.ADULT_CONTENT_PATTERN.search(message.content):
            return False, "Adult content links are not allowed"

        if len(message.content) > self.MAX_MESSAGE_LENGTH:
            return False, "Message exceeds maximum length"

        if len(message.attachments) > self.MAX_ATTACHMENTS:
            return False, "Too many attachments"

        if self.contains_blacklisted_words(message.content):
            return False, "Message contains prohibited words"

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

        if message.attachments:
            is_nsfw, score, content_type = await self.nsfw_detector.check_message(message)
            if is_nsfw:
                if isinstance(message.channel, TextChannel):
                    await self.mute_user(
                        message.author,
                        float('inf'),
                        f"NSFW {content_type} detected (Score: {score:.2f})",
                        message.channel
                    )
                return False, f"NSFW content detected"

        return True, None

    async def forward_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        if not self.is_channel_registered(message.channel.id):
            return

        ban_system = self.bot.get_cog('GlobalBanSystem')
        if ban_system and ban_system.is_banned(user_id=message.author.id):
            try:
                await message.delete()
                
                embed = discord.Embed(
                    title="Message Not Sent",
                    description="You are permanently banned from the global chat network.",
                    color=discord.Color.red(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.add_field(
                    name="Appeal",
                    value="If you believe this ban was issued in error, you can appeal in our support server.",
                    inline=False
                )
                
                view = discord.ui.View()
                view.add_item(discord.ui.Button(
                    label="Support Server",
                    style=discord.ButtonStyle.link,
                    url="https://discord.gg/HngQ9JDdmJ"
                ))
                
                try:
                    await message.author.send(embed=embed, view=view)
                except discord.Forbidden:
                    await message.channel.send(
                        embed=embed,
                        view=view,
                        delete_after=15
                    )
            except Exception as e:
                logger.error(f"Error handling banned user message: {e}")
            return

        is_valid, error_reason = await self.validate_message(message)
        if not is_valid:
            if error_reason:
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

        try:
            self.message_logs.insert_one({
                'user_id': message.author.id,
                'channel_id': message.channel.id,
                'content': message.content,
                'timestamp': datetime.now(timezone.utc),
                'attachment_count': len(message.attachments)
            })
            logger.info(f"Logged message from user {message.author.id} in channel {message.channel.id}.")
        except Exception as e:
            logger.error(f"Failed to log message from user {message.author.id}: {e}")

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

                    if not files:
                        files = []

                    logger.debug(f"Preparing to send message to webhook in channel {target_channel_id} with {len(files)} files.")

                    await webhook.send(
                        username=username,
                        avatar_url=message.author.display_avatar.url,
                        content=message.content or "",
                        files=files,
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
        await self.forward_message(message)

    async def cleanup(self) -> None:
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
        self.nsfw_detector.cleanup()

    async def cog_unload(self) -> None:
        await self.cleanup()
        logger.info("GlobalChatHandler cog unloaded.")

    async def store_report(self, report_data: dict) -> bool:
        try:
            self.reports.insert_one(report_data)
            return True
        except Exception as e:
            logger.error(f"Error storing report: {e}")
            return False

    async def get_next_report_number(self) -> int:
        try:
            result = self.reports_counter.find_one_and_update(
                {'_id': 'report_count'},
                {'$inc': {'count': 1}},
                upsert=True,
                return_document=True
            )
            return result.get('count', 1)
        except Exception as e:
            logger.error(f"Error getting next report number: {e}")
            return int(time.time())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GlobalChatHandler(bot))
    logger.info("GlobalChatHandler cog added to the bot.")
