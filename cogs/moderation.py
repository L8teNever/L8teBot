from discord.ext import commands
import discord
from discord import app_commands

class ModerationCog(commands.Cog, name="Moderation"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="kick", description="Kickt ein Mitglied vom Server.")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Kein Grund angegeben"):
        guild_id = interaction.guild.id
        config = self.bot.data.get_server_config(guild_id)
        
        # Prüfen, ob das gesamte Moderations-Modul für diesen Server aktiviert ist
        is_cog_enabled = 'Moderation' in config.get('enabled_cogs', [])
        if not is_cog_enabled:
            await interaction.response.send_message("Das Moderations-Modul ist für diesen Server deaktiviert.", ephemeral=True)
            return

        is_enabled = config.get('cogs', {}).get('Moderation', {}).get('commands', {}).get('kick', True)
        if not is_enabled:
            await interaction.response.send_message("Dieser Befehl ist auf diesem Server deaktiviert.", ephemeral=True)
            return

        try:
            await member.kick(reason=reason)
            await interaction.response.send_message(f'{member.mention} wurde erfolgreich gekickt. Grund: {reason}', ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("Ich habe nicht die nötigen Berechtigungen, um Mitglieder zu kicken.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.response.send_message(f"Ein Fehler ist aufgetreten: {e}", ephemeral=True)


    @app_commands.command(name="ban", description="Bannt ein Mitglied vom Server.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Kein Grund angegeben"):
        guild_id = interaction.guild.id
        config = self.bot.data.get_server_config(guild_id)
        
        # Prüfen, ob das gesamte Moderations-Modul für diesen Server aktiviert ist
        is_cog_enabled = 'Moderation' in config.get('enabled_cogs', [])
        if not is_cog_enabled:
            await interaction.response.send_message("Das Moderations-Modul ist für diesen Server deaktiviert.", ephemeral=True)
            return

        is_enabled = config.get('cogs', {}).get('Moderation', {}).get('commands', {}).get('ban', True)
        if not is_enabled:
            await interaction.response.send_message("Dieser Befehl ist auf diesem Server deaktiviert.", ephemeral=True)
            return

        try:
            await member.ban(reason=reason)
            await interaction.response.send_message(f'{member.mention} wurde erfolgreich gebannt. Grund: {reason}', ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("Ich habe nicht die nötigen Berechtigungen, um Mitglieder zu bannen.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.response.send_message(f"Ein Fehler ist aufgetreten: {e}", ephemeral=True)

    async def web_toggle_command(self, guild_id: int, command_name: str):
        config = self.bot.data.get_server_config(guild_id)
        
        guild_cogs_config = config.setdefault('cogs', {})
        mod_config = guild_cogs_config.setdefault('Moderation', {})
        commands_config = mod_config.setdefault('commands', {})

        current_status = commands_config.get(command_name, True)
        
        new_status = not current_status
        commands_config[command_name] = new_status
        
        self.bot.data.save_server_config(guild_id, config)
        
        status_text = 'aktiviert' if new_status else 'deaktiviert'
        return True, f"Befehl `/{command_name}` wurde erfolgreich {status_text}."

async def setup(bot):
    await bot.add_cog(ModerationCog(bot))
