import discord
from discord import app_commands
from discord.ext import commands
from pymongo import MongoClient
import os

class RemoveGlobal(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Initialize MongoDB connection
        mongodb_uri = os.getenv('MONGODB_URI')
        self.client = MongoClient(mongodb_uri)
        self.db = self.client['global_chat']
        self.servers = self.db['servers']

    @app_commands.command(name="remove", description="Remove this server from the global chat network")
    @app_commands.default_permissions(administrator=True)
    async def remove(self, interaction: discord.Interaction):
        # Check if user has admin permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions to use this command!", ephemeral=True)
            return

        try:
            # Check if server is in the database
            result = self.servers.find_one_and_delete({"guild_id": interaction.guild_id})

            if not result:
                await interaction.response.send_message("❌ This server is not connected to the global chat network!", ephemeral=True)
                return

            # Create success embed
            embed = discord.Embed(
                title="🌐 Global Chat Disconnected",
                description="This server has been successfully removed from the global chat network.",
                color=discord.Color.yellow()
            )
            embed.add_field(name="Server ID", value=interaction.guild_id, inline=True)
            embed.add_field(name="Removed By", value=interaction.user.mention, inline=True)

            # Try to send a farewell message to the channel
            try:
                channel = self.bot.get_channel(result['channel_id'])
                if channel:
                    await channel.send(embed=discord.Embed(
                        title="🌐 Global Chat Disconnected",
                        description="This channel has been disconnected from the global chat network.",
                        color=discord.Color.red()
                    ))
            except:
                pass  # Ignore if we can't send to the channel

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Error",
                description=f"An error occurred while removing the server: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(RemoveGlobal(bot))