# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import Embed, Color, Interaction, Member, Forbidden, HTTPException, TextChannel
from typing import Tuple, Optional
import datetime
import re

class GuardActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: Interaction) -> bool:
        # Nur Mitglieder mit Kick-Berechtigung können interagieren
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message("Du hast keine Berechtigung, diese Aktion auszuführen.", ephemeral=True)
            return False
            
        return True

    async def _disable_all_buttons(self, interaction: Interaction, reason: str):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        try:
            original_embed = interaction.message.embeds[0]
            original_embed.set_footer(text=f"Aktion von {interaction.user.display_name}: {reason}")
            original_embed.color = discord.Color.dark_grey()
            await interaction.message.edit(embed=original_embed, view=self)
        except (Forbidden, HTTPException, IndexError):
            pass

    async def _get_target_member(self, interaction: Interaction) -> Optional[Member]:
        try:
            embed_desc = interaction.message.embeds[0].description
            # Extrahiere ID aus `ID`
            import re
            match = re.search(r'`(\d+)`', embed_desc)
            if match:
                return interaction.guild.get_member(int(match.group(1)))
            return None
        except (IndexError, ValueError):
            return None

    @discord.ui.button(label="Genehmigen", style=discord.ButtonStyle.success, custom_id="persistent:guard:approve")
    async def approve(self, interaction: Interaction, button: discord.ui.Button):
        target_member = await self._get_target_member(interaction)
        if not target_member:
            await interaction.response.send_message("Das Mitglied wurde nicht mehr auf dem Server gefunden.", ephemeral=True)
            return
            
        await self._disable_all_buttons(interaction, "Genehmigt")
        await interaction.response.send_message(f"{interaction.user.mention} hat den Beitritt von {target_member.mention} genehmigt.", allowed_mentions=discord.AllowedMentions.none())
        
    @discord.ui.button(label="Kicken", style=discord.ButtonStyle.danger, custom_id="persistent:guard:kick")
    async def kick(self, interaction: Interaction, button: discord.ui.Button):
        target_member = await self._get_target_member(interaction)
        if not target_member:
            await interaction.response.send_message("Das Mitglied wurde nicht mehr auf dem Server gefunden.", ephemeral=True)
            return

        await self._disable_all_buttons(interaction, "Gekickt")
        try:
            await target_member.kick(reason=f"Guard-Aktion durch {interaction.user.name}")
            await interaction.response.send_message(f"{interaction.user.mention} hat {target_member.mention} gekickt.", allowed_mentions=discord.AllowedMentions.none())
        except Forbidden:
            await interaction.response.send_message("Ich habe keine Berechtigung, dieses Mitglied zu kicken.", ephemeral=True)
        except HTTPException as e:
            await interaction.response.send_message(f"Ein Fehler ist aufgetreten: {e}", ephemeral=True)

    @discord.ui.button(label="Bannen", style=discord.ButtonStyle.danger, custom_id="persistent:guard:ban")
    async def ban(self, interaction: Interaction, button: discord.ui.Button):
        target_member = await self._get_target_member(interaction)
        if not target_member:
            await interaction.response.send_message("Das Mitglied wurde nicht mehr auf dem Server gefunden.", ephemeral=True)
            return

        await self._disable_all_buttons(interaction, "Gebannt")
        try:
            await target_member.ban(reason=f"Guard-Aktion durch {interaction.user.name}")
            await interaction.response.send_message(f"{interaction.user.mention} hat {target_member.mention} gebannt.", allowed_mentions=discord.AllowedMentions.none())
        except Forbidden:
            await interaction.response.send_message("Ich habe keine Berechtigung, dieses Mitglied zu bannen.", ephemeral=True)
        except HTTPException as e:
            await interaction.response.send_message(f"Ein Fehler ist aufgetreten: {e}", ephemeral=True)

    @discord.ui.button(label="Timeout (10m)", style=discord.ButtonStyle.secondary, custom_id="persistent:guard:timeout")
    async def timeout(self, interaction: Interaction, button: discord.ui.Button):
        target_member = await self._get_target_member(interaction)
        if not target_member:
            await interaction.response.send_message("Das Mitglied wurde nicht mehr auf dem Server gefunden.", ephemeral=True)
            return

        await self._disable_all_buttons(interaction, "Timeout (10 Min)")
        try:
            await target_member.timeout(datetime.timedelta(minutes=10), reason=f"Guard-Aktion durch {interaction.user.name}")
            await interaction.response.send_message(f"{interaction.user.mention} hat {target_member.mention} für 10 Minuten in ein Timeout versetzt.", allowed_mentions=discord.AllowedMentions.none())
        except Forbidden:
            await interaction.response.send_message("Ich habe keine Berechtigung, dieses Mitglied in ein Timeout zu versetzen.", ephemeral=True)
        except HTTPException as e:
            await interaction.response.send_message(f"Ein Fehler ist aufgetreten: {e}", ephemeral=True)

class GuardCog(commands.Cog, name="Guard"):
    """Cog zum Schutz vor verdächtig neuen Accounts."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.loop.create_task(self._register_view())
    
    async def _register_view(self):
        """Registriert die persistente View nach dem Bot-Start."""
        await self.bot.wait_until_ready()
        try:
            self.bot.add_view(GuardActionView())
        except Exception as e:
            print(f"⚠️ Fehler beim Registrieren von GuardActionView: {e}")

    @commands.Cog.listener()
    async def on_member_join(self, member: Member):
        if member.bot:
            return
        
        guild_server_config = self.bot.data.get_server_config(member.guild.id)
        if "Guard" not in guild_server_config.get("enabled_cogs", []):
            return

        config = self.bot.data.get_guild_data(member.guild.id, "guard")
        if not config or config.get("action_type", "none") == "none":
            return

        account_age_days = config.get("account_age_days", 7)
        account_creation_date = member.created_at
        age_delta = datetime.datetime.now(datetime.timezone.utc) - account_creation_date
        
        if age_delta.days < account_age_days:
            action = config.get("action_type")
            
            if action == "kick":
                kick_message = config.get("kick_message", "Dein Account ist zu neu, um diesem Server beizutreten.")
                try:
                    await member.send(kick_message)
                except (Forbidden, HTTPException):
                    pass
                try:
                    await member.kick(reason=f"Guard: Account ist jünger als {account_age_days} Tage.")
                except (Forbidden, HTTPException):
                    pass

            elif action == "role":
                role_id = config.get("role_id")
                if role_id:
                    role = member.guild.get_role(role_id)
                    if role:
                        try:
                            await member.add_roles(role, reason=f"Guard: Account ist jünger als {account_age_days} Tage.")
                        except (Forbidden, HTTPException):
                            pass
            
            elif action == "alert":
                log_channel_id = config.get("log_channel_id")
                if log_channel_id:
                    channel = member.guild.get_channel(log_channel_id)
                    if isinstance(channel, TextChannel):
                        embed = Embed(
                            title="🚨 Neuer Account entdeckt",
                            description=f"Der Account von {member.mention} (`{member.id}`) ist verdächtig neu.",
                            color=Color.orange()
                        )
                        embed.add_field(name="Erstellt am", value=f"<t:{int(member.created_at.timestamp())}:F> (<t:{int(member.created_at.timestamp())}:R>)")
                        embed.add_field(name="Beigetreten am", value=f"<t:{int(member.joined_at.timestamp())}:F> (<t:{int(member.joined_at.timestamp())}:R>)")
                        embed.set_thumbnail(url=member.display_avatar.url)
                        
                        view = GuardActionView()
                        try:
                            await channel.send(embed=embed, view=view)
                        except (Forbidden, HTTPException):
                            pass

    async def web_set_config(self, guild_id: int, action_type: str, account_age_days: int, kick_message: str, role_id: Optional[int], log_channel_id: Optional[int]) -> Tuple[bool, str]:
        if account_age_days < 0:
            return False, "Das Mindestalter des Accounts muss 0 oder größer sein."

        config = self.bot.data.get_guild_data(guild_id, "guard")
        config['action_type'] = action_type
        config['account_age_days'] = account_age_days
        config['kick_message'] = kick_message
        config['role_id'] = role_id
        config['log_channel_id'] = log_channel_id
        
        self.bot.data.save_guild_data(guild_id, "guard", config)
        return True, "Guard-Einstellungen erfolgreich gespeichert."

async def setup(bot: commands.Bot):
    await bot.add_cog(GuardCog(bot))
