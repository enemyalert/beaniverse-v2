import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, List, Dict, Any
import math

class PaginationView(discord.ui.View):
    def __init__(self, pages: List[discord.Embed], timeout: float = 180):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.first_page_button.disabled = self.current_page == 0
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == len(self.pages) - 1
        self.last_page_button.disabled = self.current_page == len(self.pages) - 1

    @discord.ui.button(label="⏮️", style=discord.ButtonStyle.gray)
    async def first_page_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.blurple)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.blurple)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = min(len(self.pages) - 1, self.current_page + 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.gray)
    async def last_page_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = len(self.pages) - 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            message = await self.message.edit(view=self)
        except:
            pass

class CategorySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Connected Servers",
                value="servers",
                description="List all connected servers",
                emoji="🌐"
            ),
            discord.SelectOption(
                label="Banned Users",
                value="users",
                description="List users with mute history",
                emoji="🚫"
            )
        ]
        super().__init__(
            placeholder="Select a category to list...",
            options=options
        )

class CategoryView(discord.ui.View):
    def __init__(self, cog):
        super().__init__()
        self.cog = cog
        self.add_item(CategorySelect())
        
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

class ListCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.items_per_page = 10

    def create_server_pages(self, servers: List[Dict[str, Any]]) -> List[discord.Embed]:
        pages = []
        total_pages = math.ceil(len(servers) / self.items_per_page)

        for page in range(total_pages):
            start_idx = page * self.items_per_page
            end_idx = start_idx + self.items_per_page
            current_servers = servers[start_idx:end_idx]

            embed = discord.Embed(
                title="🌐 Beaniverse Connected Servers",
                color=discord.Color.blue(),
                description=f"Page {page + 1}/{total_pages}"
            )

            for server in current_servers:
                guild = self.bot.get_guild(server['guild_id'])
                guild_name = guild.name if guild else server['guild_name']
                channel = self.bot.get_channel(server['channel_id'])
                channel_mention = channel.mention if channel else f"#{server['channel_id']}"
                
                embed.add_field(
                    name=guild_name,
                    value=f"Channel: {channel_mention}\nInvite: {server['invite_link']}",
                    inline=False
                )

            pages.append(embed)
        return pages

    def create_user_pages(self, users: List[Dict[str, Any]]) -> List[discord.Embed]:
        pages = []
        total_pages = math.ceil(len(users) / self.items_per_page)

        for page in range(total_pages):
            start_idx = page * self.items_per_page
            end_idx = start_idx + self.items_per_page
            current_users = users[start_idx:end_idx]

            embed = discord.Embed(
                title="🚫 Beaniverse Users with Mute History",
                color=discord.Color.red(),
                description=f"Page {page + 1}/{total_pages}"
            )

            for user_data in current_users:
                user = self.bot.get_user(user_data['user_id'])
                user_name = user.name if user else f"Unknown User ({user_data['user_id']})"
                mute_count = len(user_data.get('mute_history', []))
                last_mute = user_data['mute_history'][-1] if mute_count > 0 else None
                
                value = f"Total Mutes: {mute_count}\n"
                if last_mute:
                    value += f"Last Mute Reason: {last_mute['reason']}"
                
                embed.add_field(
                    name=user_name,
                    value=value,
                    inline=False
                )

            pages.append(embed)
        return pages

    @app_commands.command(name="list", description="**Authorized user only.** List connected servers or banned users. ")
    async def list_command(self, interaction: discord.Interaction):
        view = CategoryView(self)
        
        async def select_callback(interaction: discord.Interaction):
            category = interaction.data['values'][0]
            
            handler = self.bot.get_cog('GlobalChatHandler')
            if not handler:
                await interaction.response.send_message("❌ Error: Could not access database.", ephemeral=True)
                return

            if category == "servers":
                servers = list(handler.servers.find({}))
                if not servers:
                    await interaction.response.send_message("No servers are currently connected.", ephemeral=True)
                    return
                pages = self.create_server_pages(servers)

            elif category == "users":
                banned_users = list(handler.users.find({"mute_history": {"$exists": True}}))
                if not banned_users:
                    await interaction.response.send_message("No users have been muted.", ephemeral=True)
                    return
                pages = self.create_user_pages(banned_users)

            if not pages:
                await interaction.response.send_message("No data to display.", ephemeral=True)
                return

            pagination_view = PaginationView(pages)
            await interaction.response.send_message(embed=pages[0], view=pagination_view, ephemeral=True)

        view.children[0].callback = select_callback
        await interaction.response.send_message("Please select a category to list:", view=view, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(ListCommands(bot))
