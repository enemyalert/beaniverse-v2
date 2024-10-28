import discord
from discord import app_commands
from discord.ext import commands
from pymongo import MongoClient
import os

class GlobalChat(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Initialize MongoDB connection
        mongodb_uri = os.getenv('MONGODB_URI')
        self.client = MongoClient(mongodb_uri)
        self.db = self.client['global_chat']
        self.servers = self.db['servers']

    @app_commands.command(name="add", description="Add this server to the global chat network")
    @app_commands.default_permissions(administrator=True)
    async def add(self, interaction: discord.Interaction, channel: discord.TextChannel):
        # Check if user has admin permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions to use this command!", ephemeral=True)
            return

        try:
            # Get server invite
            invite = await channel.create_invite(max_age=0, max_uses=0)

            # Check if server is already in the database
            existing_server = self.servers.find_one({"guild_id": interaction.guild_id})
            if existing_server:
                await interaction.response.send_message("❌ This server is already connected to the global chat network!", ephemeral=True)
                return

            # Store server info in MongoDB
            server_data = {
                "guild_id": interaction.guild_id,
                "guild_name": interaction.guild.name,
                "channel_id": channel.id,
                "invite_link": invite.url,
                "added_by": interaction.user.id,
                "added_at": discord.utils.utcnow().isoformat()
            }

            self.servers.insert_one(server_data)

            # Create success embed
            embed = discord.Embed(
                title="🌐 Global Chat Connected!",
                description="This server has been successfully connected to the global chat network.",
                color=discord.Color.green()
            )
            embed.add_field(name="Channel", value=channel.mention, inline=True)
            embed.add_field(name="Server ID", value=interaction.guild_id, inline=True)
            embed.add_field(name="Added By", value=interaction.user.mention, inline=True)

            await interaction.response.send_message(embed=embed)

            # Send a test message to the channel
            welcome_embed = discord.Embed(
                title="🌐 Global Chat System",
                description="This channel has been successfully connected to the global chat network!",
                color=discord.Color.blue()
            )
            welcome_embed.add_field(name="Commands", value="Use `/remove` to disconnect from the network", inline=False)
            await channel.send(embed=welcome_embed)

        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Error",
                description=f"An error occurred while adding the server: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(GlobalChat(bot))