import discord
from discord import app_commands
from discord.ext import commands
from pymongo import MongoClient
import os

class GlobalChat(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        mongodb_uri = os.getenv('MONGODB_URI')
        self.client = MongoClient(mongodb_uri)
        self.db = self.client['global_chat']
        self.servers = self.db['servers']

    @app_commands.command(name="joinbeaniverse", description="**Admin permission required.** Add this server to the Beaniverse network.")
    @app_commands.default_permissions(administrator=True)
    async def joinbeaniverse(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions to use this command!", ephemeral=True)
            return

        try:
            invite = await channel.create_invite(max_age=0, max_uses=0)

            existing_server = self.servers.find_one({"guild_id": interaction.guild_id})
            if existing_server:
                await interaction.response.send_message("❌ This server is already connected to the Beaniverse network!", ephemeral=True)
                return

            server_data = {
                "guild_id": interaction.guild_id,
                "guild_name": interaction.guild.name,
                "channel_id": channel.id,
                "invite_link": invite.url,
                "added_by": interaction.user.id,
                "added_at": discord.utils.utcnow().isoformat()
            }

            self.servers.insert_one(server_data)

            embed = discord.Embed(
                title="🌐 Beaniverse Connected!",
                description="This server has been successfully connected to the Beaniverse network.",
                color=discord.Color.green()
            )
            embed.add_field(name="Channel", value=channel.mention, inline=True)
            embed.add_field(name="Server ID", value=interaction.guild_id, inline=True)
            embed.add_field(name="Added By", value=interaction.user.mention, inline=True)

            await interaction.response.send_message(embed=embed)

            welcome_embed = discord.Embed(
                title="🌐 Beaniverse System",
                description="This channel has been successfully connected to the Beaniverse network!",
                color=discord.Color.blue()
            )
            welcome_embed.add_field(name="Commands", value="Use `/leavebeaniverse` to disconnect from the network", inline=False)
            await channel.send(embed=welcome_embed)

        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Error",
                description=f"An error occurred while adding the server: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)

    @app_commands.command(name="leavebeaniverse", description="**Admin permission required.** Remove this server from the Beaniverse network.")
    @app_commands.default_permissions(administrator=True)
    async def leavebeaniverse(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions to use this command!", ephemeral=True)
            return

        try:
            result = self.servers.find_one_and_delete({"guild_id": interaction.guild_id})

            if not result:
                await interaction.response.send_message("❌ This server is not connected to the Beaniverse network!", ephemeral=True)
                return

            embed = discord.Embed(
                title="🌐 Beaniverse Disconnected",
                description="This server has been successfully removed from the Beaniverse network.",
                color=discord.Color.yellow()
            )
            embed.add_field(name="Server ID", value=interaction.guild_id, inline=True)
            embed.add_field(name="Removed By", value=interaction.user.mention, inline=True)

            try:
                channel = self.bot.get_channel(result['channel_id'])
                if channel:
                    await channel.send(embed=discord.Embed(
                        title="🌐 Beaniverse Disconnected",
                        description="This channel has been disconnected from the Beaniverse network.",
                        color=discord.Color.red()
                    ))
            except:
                pass

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Error",
                description=f"An error occurred while removing the server: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(GlobalChat(bot))
