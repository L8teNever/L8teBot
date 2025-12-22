# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands, Embed, Color, TextChannel, Member, User, Forbidden, HTTPException
from typing import Optional, Tuple

class GlobalBanView(discord.ui.View):
    """
    Buttons für die Interaktion mit einer Global-Ban-Benachrichtigung.
    """
    def __init__(self, bot: commands.Bot, target_user_id: int, source_guild_name: str, reason: str, is_temp_channel: bool):
        super().__init__(timeout=60 * 60 * 24 * 7) # 7 Tage Timeout
        self.bot = bot
        self.target_user_id = target_user_id
        self.source_guild_name = source_guild_name
        self.reason = reason
        self.is_temp_channel = is_temp_channel

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Nur Admins können die Buttons benutzen
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Du hast keine Berechtigung, diese Aktion auszuführen.", ephemeral=True)
            return False
        return True

    async def handle_action(self, interaction: discord.Interaction):
        """Gemeinsame Logik nach einer Button-Aktion."""
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        
        if self.is_temp_channel and interaction.channel:
            try:
                # Kurze Verzögerung, damit die ephemere Nachricht ankommt
                await discord.utils.sleep_until(discord.utils.utcnow() + discord.utils.timedelta(seconds=5))
                await interaction.channel.delete(reason="Global-Ban-Aktion abgeschlossen.")
            except (Forbidden, HTTPException):
                pass

    @discord.ui.button(label="Auf diesem Server bannen", style=discord.ButtonStyle.danger)
    async def ban_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            target_user = self.bot.get_user(self.target_user_id) or await self.bot.fetch_user(self.target_user_id)
        except HTTPException:
            await interaction.followup.send("Fehler: Konnte den Benutzer nicht von Discord abrufen.", ephemeral=True)
            return

        guild = interaction.guild
        
        if not guild.me.guild_permissions.ban_members:
            await interaction.followup.send("Ich habe keine Berechtigung, Mitglieder auf diesem Server zu bannen.", ephemeral=True)
            return

        try:
            await guild.ban(target_user, reason=f"Global Ban von {self.source_guild_name}. Ursprünglicher Grund: {self.reason}")
            await interaction.followup.send(f"✅ {target_user.mention} ({target_user.name}) wurde auf diesem Server gebannt.", ephemeral=True)
        except Forbidden:
            await interaction.followup.send("Fehler: Ich konnte den User nicht bannen. Möglicherweise hat er eine höhere Rolle als ich.", ephemeral=True)
        except HTTPException as e:
            await interaction.followup.send(f"Ein API-Fehler ist aufgetreten: {e}", ephemeral=True)
        
        await self.handle_action(interaction)

    @discord.ui.button(label="Nichts unternehmen", style=discord.ButtonStyle.secondary)
    async def ignore_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            target_user = self.bot.get_user(self.target_user_id) or await self.bot.fetch_user(self.target_user_id)
            await interaction.followup.send(f"ℹ️ Es wurde keine Aktion gegen {target_user.mention} ({target_user.name}) unternommen.", ephemeral=True)
        except HTTPException:
            await interaction.followup.send("ℹ️ Es wurde keine Aktion unternommen.", ephemeral=True)
        await self.handle_action(interaction)


class GlobalBanCog(commands.Cog, name="Global-Ban"):
    """
    Cog für das serverübergreifende Bannen von Usern.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="globalban", description="Bannt einen User auf diesem und potenziell anderen Servern.")
    @app_commands.describe(user="Der zu bannende User", reason="Der Grund für den Bann.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def globalban(self, interaction: discord.Interaction, user: Member, reason: str):
        await interaction.response.defer(ephemeral=True)

        source_guild = interaction.guild
        
        # 1. User auf dem aktuellen Server bannen
        try:
            await source_guild.ban(user, reason=f"Global Ban ausgelöst von {interaction.user.name}. Grund: {reason}")
        except Forbidden:
            await interaction.followup.send("Ich konnte den User nicht bannen. Überprüfe meine Rollenposition und Berechtigungen.", ephemeral=True)
            return
        except HTTPException as e:
            await interaction.followup.send(f"Ein Fehler ist beim Bannen aufgetreten: {e}", ephemeral=True)
            return

        await interaction.followup.send(f"✅ {user.mention} wurde auf diesem Server gebannt. Die Benachrichtigung wird an andere Server gesendet.", ephemeral=True)

        # 2. Andere Server benachrichtigen
        for guild in self.bot.guilds:
            if guild.id == source_guild.id:
                continue

            guild_config = self.bot.data.get_server_config(guild.id)
            is_enabled = 'Global-Ban' in guild_config.get('enabled_cogs', [])
            if not is_enabled:
                continue

            me = guild.me
            if not me.guild_permissions.ban_members or not me.guild_permissions.manage_channels:
                continue

            # Load Global Ban config
            gb_config = self.bot.data.get_guild_data(guild.id, "global_ban")
            log_channel_id = gb_config.get("log_channel_id")
            log_channel = None
            is_temp_channel = False

            if log_channel_id:
                log_channel = guild.get_channel(log_channel_id)
                if not isinstance(log_channel, TextChannel):
                    log_channel = None

            if not log_channel:
                is_temp_channel = True
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                }
                for role in guild.roles:
                    if role.permissions.administrator:
                        overwrites[role] = discord.PermissionOverwrite(read_messages=True)
                
                try:
                    log_channel = await guild.create_text_channel(
                        name=f"🚨-global-ban-{user.name.lower()}",
                        overwrites=overwrites,
                        reason=f"Global-Ban-Benachrichtigung für {user.name}"
                    )
                except (Forbidden, HTTPException):
                    continue
            
            embed = Embed(
                title="🚨 Global-Ban-Benachrichtigung",
                description=f"Der User **{user.name}** (`{user.id}`) wurde auf dem Server **{source_guild.name}** gebannt.",
                color=Color.red(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Grund", value=reason, inline=False)
            embed.add_field(name="Aktion", value="Möchtest du diesen User auch von diesem Server bannen?", inline=False)
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.set_footer(text=f"Ausgelöst von: {interaction.user.name}")

            view = GlobalBanView(self.bot, user.id, source_guild.name, reason, is_temp_channel)

            try:
                message = await log_channel.send(embed=embed, view=view)
            except (Forbidden, HTTPException):
                # Log the error for debugging purposes
                print(f"Failed to send message to channel {log_channel.id} in guild {guild.id}")
                if is_temp_channel:
                    try: await log_channel.delete()
                    except: pass

    # --- Web API Methoden ---
    async def web_set_config(self, guild_id: int, channel_id: Optional[int]) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return False, "Server nicht gefunden."

        config = self.bot.data.get_guild_data(guild_id, "global_ban")
        config['log_channel_id'] = channel_id
        self.bot.data.save_guild_data(guild_id, "global_ban", config)
        
        if channel_id:
            channel = guild.get_channel(channel_id)
            return True, f"Global-Ban-Log-Kanal wurde auf {channel.mention} gesetzt."
        else:
            return True, "Global-Ban-Log-Kanal wurde entfernt. Es werden nun temporäre Kanäle erstellt."

async def setup(bot: commands.Bot):
    await bot.add_cog(GlobalBanCog(bot))