import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, List, Dict, Any
from pymongo import MongoClient
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

AUTHORIZED_USERS = [int(id.strip()) for id in os.getenv('AUTHORIZED_USERS', '').split(',')]

class BeaniverseBanSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        mongodb_uri = os.getenv('MONGODB_URI')
        if not mongodb_uri:
            raise ValueError("MONGODB_URI not found in environment variables")

        self.client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
        self.db = self.client['global_chat']
        self.bans = self.db['bans']

        self.setup_indexes()

    def setup_indexes(self) -> None:
        try:
            self.bans.create_index("user_id")
            self.bans.create_index("server_id")
            print("Ban system indexes created successfully!")
        except Exception as e:
            print(f"Error creating ban system indexes: {e}")

    def is_banned(self, user_id: Optional[int] = None, server_id: Optional[int] = None) -> bool:
        if user_id:
            return bool(self.bans.find_one({"user_id": user_id, "active": True}))
        if server_id:
            return bool(self.bans.find_one({"server_id": server_id, "active": True}))
        return False

    async def check_permissions(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in AUTHORIZED_USERS:
            await interaction.response.send_message(
                "You don't have permission to use this command.", 
                ephemeral=True
            )
            return False
        return True

    async def announce_to_registered_channels(self, user: discord.User, reason: str, banned_by: discord.User, action: str = "banned"):
        embed = discord.Embed(
            title=f"🚫 Beaniverse {'Ban' if action == 'banned' else 'Unban'} Notification",
            description=f"A user has been {action} from the Beaniverse network.",
            color=discord.Color.red() if action == "banned" else discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(
            name=f"{action.title()} User",
            value=f"{user.mention} (`{user.name}`)",
            inline=True
        )
        
        if action == "banned":
            embed.add_field(
                name=f"{action.title()} By",
                value=banned_by.mention,
                inline=True
            )
            embed.add_field(
                name="Reason",
                value=reason,
                inline=False
            )
        
        registered_channels = self.db['servers'].find()
        for channel_data in registered_channels:
            channel_id = channel_data.get('channel_id')
            channel = self.bot.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(embed=embed)
                except Exception as e:
                    print(f"Failed to send {action} notification to channel {channel_id}: {e}")

    async def send_dm(self, user: discord.User, embed: discord.Embed, view: Optional[discord.ui.View] = None):
        try:
            if view:
                await user.send(embed=embed, view=view)
            else:
                await user.send(embed=embed)
        except discord.Forbidden:
            print(f"Could not send DM to {user.name} ({user.id})")

    @app_commands.command(name="ban", description="**Authorized user only.** Ban a user from using Beaniverse. ")
    async def ban(self, interaction: discord.Interaction):
        if not await self.check_permissions(interaction):
            return
        
        await interaction.response.send_modal(BanModal())

    async def handle_ban_modal(self, interaction: discord.Interaction, user_id: int, reason: str):
        try:
            user = await self.bot.fetch_user(user_id)
            
            if not user:
                await interaction.response.send_message("Could not find user with that ID.", ephemeral=True)
                return
                
            if self.is_banned(user_id=user.id):
                await interaction.response.send_message(f"{user.mention} is already banned.", ephemeral=True)
                return

            confirm = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.danger)
            cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
            view = discord.ui.View(timeout=60)
            view.add_item(confirm)
            view.add_item(cancel)

            async def confirm_callback(button_interaction: discord.Interaction):
                if button_interaction.user.id != interaction.user.id:
                    await button_interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
                    return

                db_ban_data = {
                    "user_id": user.id,
                    "user_name": str(user),
                    "banned_by": interaction.user.id,
                    "reason": reason,
                    "timestamp": datetime.utcnow(),
                    "active": True
                }

                self.bans.insert_one(db_ban_data)
                
                embed = discord.Embed(
                    title="Message Not Sent",
                    description="You are permanently banned from the Beaniverse network.",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Reason", value=reason, inline=False)
                embed.add_field(name="Banned By", value=interaction.user.mention, inline=False)
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

                await self.send_dm(user, embed, view)
                
                await self.announce_to_registered_channels(user, reason, interaction.user, "banned")
                
                await button_interaction.response.edit_message(content="Ban confirmed.", view=None)

            async def cancel_callback(button_interaction: discord.Interaction):
                await button_interaction.response.edit_message(content="Ban action cancelled.", view=None)

            confirm.callback = confirm_callback
            cancel.callback = cancel_callback

            embed = discord.Embed(
                title="Confirm Beaniverse Ban",
                color=discord.Color.yellow(),
                description="Are you sure you want to proceed with this ban?"
            )
            embed.add_field(name="Target User", value=f"{user.mention} ({user.id})")
            embed.add_field(name="Reason", value=reason)

            await interaction.response.send_message(embed=embed, view=view)
            
        except Exception as e:
            await interaction.response.send_message(f"An error occurred: {str(e)}", ephemeral=True)

    @app_commands.command(name="unban", description="**Authorized user only**. Unban a user from Beaniverse.")    
    async def unban(self, interaction: discord.Interaction):
        if not await self.check_permissions(interaction):
            return

        banned_users = list(self.bans.find({"active": True}))
        if not banned_users:
            await interaction.response.send_message("There are no banned users.", ephemeral=True)
            return

        select_menu = BannedUserSelect(banned_users)
        
        view = discord.ui.View(timeout=60)
        view.add_item(select_menu)

        async def select_callback(select_interaction: discord.Interaction):
            user_id = int(select_interaction.data["values"][0])
            user = await self.bot.fetch_user(user_id)
            
            if not user:
                await select_interaction.response.send_message("Could not find user.", ephemeral=True)
                return

            confirm = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.success)
            cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
            unban_view = discord.ui.View(timeout=60)
            unban_view.add_item(confirm)
            unban_view.add_item(cancel)

            async def confirm_callback(button_interaction: discord.Interaction):
                if button_interaction.user.id != select_interaction.user.id:
                    await button_interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
                    return

                self.bans.update_one(
                    {"user_id": user.id, "active": True},
                    {"$set": {"active": False, "unbanned_by": select_interaction.user.id, "unban_time": datetime.utcnow()}}
                )

                embed = discord.Embed(
                    title="Beaniverse Unban",
                    description="You have been unbanned from the Beaniverse network.",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(
                    name="Unbanned By",
                    value=select_interaction.user.mention,
                    inline=False
                )

                view = discord.ui.View()
                view.add_item(discord.ui.Button(
                    label="Support Server",
                    style=discord.ButtonStyle.link,
                    url="https://discord.gg/HngQ9JDdmJ"
                ))

                await self.send_dm(user, embed, view)
                
                await self.announce_to_registered_channels(user, "", interaction.user, "unbanned")
                
                await button_interaction.response.edit_message(content=f"Successfully unbanned {user.mention}", view=None)

            async def cancel_callback(button_interaction: discord.Interaction):
                await button_interaction.response.edit_message(content="Unban action cancelled.", view=None)

            confirm.callback = confirm_callback
            cancel.callback = cancel_callback

            embed = discord.Embed(
                title="Confirm Beaniverse Unban",
                color=discord.Color.yellow(),
                description="Are you sure you want to unban this user?"
            )
            embed.add_field(name="Target User", value=f"{user.mention} ({user.id})")

            await select_interaction.response.edit_message(embed=embed, view=unban_view)

        select_menu.callback = select_callback
        await interaction.response.send_message("Select a user to unban:", view=view, ephemeral=True)

    async def cog_unload(self) -> None:
        self.client.close()

async def setup(bot: commands.Bot):
    await bot.add_cog(BeaniverseBanSystem(bot))

class BannedUserSelect(discord.ui.Select):
    def __init__(self, banned_users: List[Dict[str, Any]]):
        options = []
        for user_data in banned_users[:25]:
            user_id = user_data["user_id"]
            user_name = user_data.get("user_name", f"Unknown User ({user_id})")
            options.append(
                discord.SelectOption(
                    label=user_name,
                    value=str(user_id),
                    description=f"ID: {user_id}"
                )
            )
            
        super().__init__(
            placeholder="Select a user to unban...",
            options=options,
            min_values=1,
            max_values=1
        )

class BanModal(discord.ui.Modal, title="Beaniverse Ban Form"):
    def __init__(self):
        super().__init__()
        
        self.add_item(discord.ui.TextInput(
            label="User ID",
            placeholder="Enter the user ID to ban",
            style=discord.TextStyle.short,
            required=True,
            max_length=20
        ))
        
        self.add_item(discord.ui.TextInput(
            label="Reason",
            placeholder="Enter the reason for the ban",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000
        ))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_id = int(self.children[0].value)
            reason = self.children[1].value
            
            ban_system = interaction.client.get_cog('BeaniverseBanSystem')
            if not ban_system:
                await interaction.response.send_message("Ban system is currently unavailable.", ephemeral=True)
                return
                
            await ban_system.handle_ban_modal(interaction, user_id, reason)
            
        except ValueError:
            await interaction.response.send_message("Invalid user ID format.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"An error occurred: {str(e)}", ephemeral=True)
