import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
from pymongo import MongoClient
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

AUTHORIZED_USER_ID = 624471886054686731

class GlobalBanSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # MongoDB setup
        mongodb_uri = os.getenv('MONGODB_URI')
        if not mongodb_uri:
            raise ValueError("MONGODB_URI not found in environment variables")

        self.client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
        self.db = self.client['global_chat']
        self.bans = self.db['bans']

        # Set up indexes
        self.setup_indexes()

    def setup_indexes(self) -> None:
        """Setup MongoDB indexes for the bans collection."""
        try:
            self.bans.create_index("user_id")
            self.bans.create_index("server_id")
            print("Ban system indexes created successfully!")
        except Exception as e:
            print(f"Error creating ban system indexes: {e}")

    def is_banned(self, user_id: Optional[int] = None, server_id: Optional[int] = None) -> bool:
        """Check if a user or server is banned."""
        if user_id:
            return bool(self.bans.find_one({"user_id": user_id, "active": True}))
        if server_id:
            return bool(self.bans.find_one({"server_id": server_id, "active": True}))
        return False

    async def check_permissions(self, interaction: discord.Interaction) -> bool:
        """Check if the user has permission to use ban commands."""
        if interaction.user.id != AUTHORIZED_USER_ID:
            await interaction.response.send_message(
                "You don't have permission to use this command.", 
                ephemeral=True
            )
            return False
        return True

    async def announce_to_registered_channels(self, message: str):
        """Announce a message to all registered channels."""
        registered_channels = self.db['registered_channels'].find()
        for channel_data in registered_channels:
            channel_id = channel_data.get('channel_id')
            channel = self.bot.get_channel(channel_id)
            if channel:
                await channel.send(message)

    async def send_dm(self, user: discord.User, embed: discord.Embed):
        """Send a DM to a banned/unbanned user."""
        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            print(f"Could not send DM to {user.name} ({user.id})")

    @app_commands.command(name="banglobal", description="Ban a user or server from using global chat")
    async def banglobal(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.User] = None,
        server_id: Optional[str] = None,
        reason: str = "No reason provided"
    ):
        if not await self.check_permissions(interaction):
            return

        if user and self.is_banned(user_id=user.id):
            await interaction.response.send_message(f"{user.mention} is already banned.", ephemeral=True)
            return

        if server_id:
            try:
                server_id_int = int(server_id)
                if self.is_banned(server_id=server_id_int):
                    await interaction.response.send_message(f"Server {server_id} is already banned.", ephemeral=True)
                    return
            except ValueError:
                await interaction.response.send_message("Invalid server ID format.", ephemeral=True)
                return

        confirm = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.danger)
        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        view = discord.ui.View(timeout=60)
        view.add_item(confirm)
        view.add_item(cancel)

        ban_data = {"user": user, "server_id": server_id, "reason": reason, "interaction": interaction}

        async def confirm_callback(button_interaction: discord.Interaction):
            if button_interaction.user.id != interaction.user.id:
                await button_interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
                return

            db_ban_data = {
                "banned_by": interaction.user.id,
                "reason": reason,
                "timestamp": datetime.utcnow(),
                "active": True
            }

            if user:
                db_ban_data["user_id"] = user.id
                db_ban_data["user_name"] = str(user)
                self.bans.insert_one(db_ban_data)
                embed = discord.Embed(
                    title="You have been banned from Global Chat",
                    description=f"You were banned for the following reason: {reason}",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Banned By", value=interaction.user.mention)
                await self.send_dm(user, embed)
                await self.announce_to_registered_channels(f"User {user.mention} has been banned from global chat.")

            elif server_id:
                db_ban_data["server_id"] = int(server_id)
                self.bans.insert_one(db_ban_data)
                await self.announce_to_registered_channels(f"Server {server_id} has been banned from global chat.")

            await button_interaction.response.edit_message(content="Ban confirmed.", view=None)

        async def cancel_callback(button_interaction: discord.Interaction):
            await button_interaction.response.edit_message(content="Ban action cancelled.", view=None)

        confirm.callback = confirm_callback
        cancel.callback = cancel_callback

        embed = discord.Embed(
            title="Confirm Global Chat Ban",
            color=discord.Color.yellow(),
            description="Are you sure you want to proceed with this ban?"
        )
        if user:
            embed.add_field(name="Target User", value=f"{user.mention} ({user.id})")
        else:
            embed.add_field(name="Target Server", value=server_id)
        embed.add_field(name="Reason", value=reason)

        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="unbanglobal", description="Unban a user or server from global chat")
    async def unbanglobal(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.User] = None,
        server_id: Optional[str] = None,
        reason: str = "No reason provided"
    ):
        if not await self.check_permissions(interaction):
            return

        confirm = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.success)
        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        view = discord.ui.View(timeout=60)
        view.add_item(confirm)
        view.add_item(cancel)

        unban_data = {"user": user, "server_id": server_id, "reason": reason}

        async def confirm_callback(button_interaction: discord.Interaction):
            if user:
                query = {"user_id": user.id, "active": True}
            else:
                try:
                    query = {"server_id": int(server_id), "active": True}
                except ValueError:
                    await button_interaction.response.send_message("Invalid server ID format.", ephemeral=True)
                    return

            ban_doc = self.bans.find_one(query)
            if not ban_doc:
                await button_interaction.response.send_message("No active ban found.", ephemeral=True)
                return

            self.bans.delete_one({"_id": ban_doc["_id"]})

            if user:
                embed = discord.Embed(
                    title="You have been unbanned from Global Chat",
                    description=f"You were unbanned for the following reason: {reason}",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Unbanned By", value=interaction.user.mention)
                await self.send_dm(user, embed)
                await self.announce_to_registered_channels(f"User {user.mention} has been unbanned from global chat.")

            else:
                await self.announce_to_registered_channels(f"Server {server_id} has been unbanned from global chat.")

            await button_interaction.response.edit_message(content="Unban confirmed.", view=None)

        async def cancel_callback(button_interaction: discord.Interaction):
            await button_interaction.response.edit_message(content="Unban action cancelled.", view=None)

        confirm.callback = confirm_callback
        cancel.callback = cancel_callback

        embed = discord.Embed(
            title="Confirm Global Chat Unban",
            color=discord.Color.yellow(),
            description="Are you sure you want to proceed with this unban?"
        )
        if user:
            embed.add_field(name="Target User", value=f"{user.mention} ({user.id})")
        else:
            embed.add_field(name="Target Server", value=server_id)
        embed.add_field(name="Reason", value=reason)

        await interaction.response.send_message(embed=embed, view=view)

    async def cog_unload(self) -> None:
        """Cleanup when cog is unloaded."""
        self.client.close()

async def setup(bot: commands.Bot):
    await bot.add_cog(GlobalBanSystem(bot))
