import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, List
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
import logging
import time

load_dotenv()

REPORT_CHANNEL_ID = 1300436583467450509
AUTHORIZED_USERS = [int(id.strip()) for id in os.getenv('AUTHORIZED_USERS', '').split(',')]

class BanButton(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="Ban User", style=discord.ButtonStyle.danger)
    async def ban_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in AUTHORIZED_USERS:
            await interaction.response.send_message("You don't have permission to ban users.", ephemeral=True)
            return

        try:
            ban_system = interaction.client.get_cog('GlobalBanSystem')
            if not ban_system:
                await interaction.response.send_message("Ban system is currently unavailable.", ephemeral=True)
                return

            user = await interaction.client.fetch_user(self.user_id)
            if not user:
                await interaction.response.send_message("Could not find user to ban.", ephemeral=True)
                return

            confirm = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.success)
            cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
            view = discord.ui.View(timeout=60)
            view.add_item(confirm)
            view.add_item(cancel)

            async def confirm_callback(button_interaction: discord.Interaction):
                if button_interaction.user.id != interaction.user.id:
                    await button_interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
                    return

                try:
                    db_ban_data = {
                        "user_id": user.id,
                        "user_name": str(user),
                        "banned_by": interaction.user.id,
                        "reason": "Banned from report",
                        "timestamp": datetime.utcnow(),
                        "active": True
                    }

                    ban_system.bans.insert_one(db_ban_data)

                    embed = discord.Embed(
                        title="You have been banned from Beaniverse",
                        description=f"You were banned for the following reason: Banned from report",
                        color=discord.Color.red(),
                        timestamp=datetime.utcnow()
                    )
                    embed.add_field(name="Banned By", value=interaction.user.mention)
                    try:
                        await user.send(embed=embed)
                    except:
                        pass

                    await ban_system.announce_to_registered_channels(f"User {user.mention} has been banned from Beaniverse.")

                    button.disabled = True
                    await interaction.message.edit(view=self)

                    await button_interaction.response.edit_message(content="Ban executed successfully.", view=None)

                except Exception as e:
                    await button_interaction.response.send_message(f"Error executing ban: {str(e)}", ephemeral=True)

            async def cancel_callback(button_interaction: discord.Interaction):
                await button_interaction.response.edit_message(content="Ban cancelled.", view=None)

            confirm.callback = confirm_callback
            cancel.callback = cancel_callback

            embed = discord.Embed(
                title="Confirm Beaniverse Ban",
                color=discord.Color.yellow(),
                description="Are you sure you want to proceed with this ban?"
            )
            embed.add_field(name="Target User", value=f"{user.mention} ({user.id})")
            embed.add_field(name="Reason", value="Banned from report")

            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"An error occurred while banning: {str(e)}", ephemeral=True)

class ReportModal(discord.ui.Modal, title="Beaniverse Report"):
    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot
        
        self.add_item(discord.ui.TextInput(
            label="Reported User ID",
            style=discord.TextStyle.short,
            placeholder="Enter the user ID of the person you're reporting",
            required=True,
            max_length=20
        ))
        
        self.add_item(discord.ui.TextInput(
            label="Any complaint?",
            style=discord.TextStyle.paragraph,
            placeholder="your content here",
            required=True,
            max_length=2000
        ))

    async def get_next_report_number(self) -> int:
        try:
            handler = self.bot.get_cog('GlobalChatHandler')
            if not handler:
                return int(time.time())
            return await handler.get_next_report_number()
        except Exception as e:
            logging.error(f"Error getting report number: {e}")
            return int(time.time())

    async def on_submit(self, interaction: discord.Interaction):
        try:
            handler = self.bot.get_cog('GlobalChatHandler')
            if not handler:
                await interaction.response.send_message(
                    "Error: Could not access database. Please try again later.",
                    ephemeral=True
                )
                return

            report_channel = interaction.client.get_channel(REPORT_CHANNEL_ID)
            if not report_channel:
                await interaction.response.send_message(
                    "Error: Report channel not found. Please contact an administrator.",
                    ephemeral=True
                )
                return

            report_number = await self.get_next_report_number()

            embed = discord.Embed(
                title=f"New Report #{report_number}",
                color=discord.Color.red(),
                timestamp=interaction.created_at
            )
            
            reported_user_id = int(self.children[0].value)
            embed.add_field(name="Reported User", value=f"<@{reported_user_id}> ({reported_user_id})", inline=False)
            embed.add_field(name="Complainant", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False)
            embed.add_field(name="Description", value=self.children[1].value, inline=False)
            
            if interaction.guild:
                embed.add_field(
                    name="Server",
                    value=f"{interaction.guild.name} ({interaction.guild.id})",
                    inline=False
                )

            view = BanButton(reported_user_id)

            await report_channel.send(embed=embed, view=view)
            
            await interaction.response.send_message(
                "Your report has been submitted successfully!",
                ephemeral=True
            )

            report_data = {
                "report_number": report_number,
                "reported_user_id": reported_user_id,
                "reporter_id": interaction.user.id,
                "description": self.children[1].value,
                "server_id": interaction.guild.id if interaction.guild else None,
                "timestamp": interaction.created_at.isoformat()
            }
            
            await handler.store_report(report_data)

        except ValueError as ve:
            await interaction.response.send_message(
                f"Invalid user ID format. Please enter a valid user ID.",
                ephemeral=True
            )
        except Exception as e:
            logging.error(f"Error processing report: {e}")
            await interaction.response.send_message(
                "An error occurred while processing your report. Please try again later.",
                ephemeral=True
            )

class ReportSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.report_cooldowns = {}
        self.REPORT_COOLDOWN = 300

    @app_commands.command(
        name="reportbeaniverse",
        description="Submit a report about Beaniverse"
    )
    async def report(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        now = datetime.now()
        if user_id in self.report_cooldowns:
            time_diff = now - self.report_cooldowns[user_id]
            if time_diff < timedelta(seconds=self.REPORT_COOLDOWN):
                remaining = self.REPORT_COOLDOWN - time_diff.seconds
                await interaction.response.send_message(
                    f"Please wait {remaining} seconds before submitting another report.",
                    ephemeral=True
                )
                return

        self.report_cooldowns[user_id] = now
        await interaction.response.send_modal(ReportModal())

async def setup(bot: commands.Bot):
    await bot.add_cog(ReportSystem(bot))
