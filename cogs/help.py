import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, Mapping

class HelpCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
    @app_commands.command(
        name="help",
        description="Shows information about Beaniverse commands"
    )
    async def help_command(
        self, 
        interaction: discord.Interaction
    ):
        await interaction.response.defer()
        
        embed = discord.Embed(
            title="Beaniverse Help",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        
        embed.set_author(
            name=self.bot.user.name if self.bot.user else "Beaniverse",
            icon_url=self.bot.user.avatar.url if self.bot.user and self.bot.user.avatar else None
        )
        
        embed.set_image(url="attachment://beaniverse.gif")
        
        embed.description = "Here are all available Beaniverse commands:"
        
        commands_list = []
        for cmd in sorted(self.bot.tree.get_commands(), key=lambda x: x.name.lower()):
            commands_list.append(f"\n`/{cmd.name}`\n> {cmd.description}")
        
        embed.add_field(
            name="Commands \n",
            value="\n".join(commands_list),
            inline=False
        )
        
        total_commands = len(self.bot.tree.get_commands())
        embed.set_footer(
            text=f"{total_commands} commands",
            icon_url=interaction.user.avatar.url if interaction.user.avatar else None
        )
        
        file = discord.File("assets/beaniverse.gif", filename="beaniverse.gif")
        await interaction.followup.send(file=file, embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCommand(bot))
