import discord
from discord import app_commands
from discord.ext import commands

class Ping(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Check Beaniverse's latency")
    async def ping(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🌐 Beaniverse Latency",
            color=discord.Color.blue()
        )
        embed.add_field(name="Response Time", value=f"{round(self.bot.latency * 1000)}ms", inline=False)

        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Ping(bot))