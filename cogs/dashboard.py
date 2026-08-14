import discord
from discord.ext import commands
from discord import app_commands, Embed, Color, TextStyle, Interaction, ButtonStyle, ForumChannel, CategoryChannel
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger('DashboardCog')

# --- MODALS ---

class DashboardBanModal(discord.ui.Modal):
    def __init__(self, target_id: int, target_name: str, cog_instance: commands.Cog):
        super().__init__(title=f"User bannen: {target_name[:20]}")
        self.target_id = target_id
        self.target_name = target_name
        self.cog = cog_instance

        self.reason_input = discord.ui.TextInput(
            label="Bann-Grund",
            style=TextStyle.long,
            placeholder="Grund für den Bann eingeben (z.B. Regelverstoß)...",
            required=False,
            max_length=500
        )
        self.add_item(self.reason_input)

        self.delete_days_input = discord.ui.TextInput(
            label="Nachrichten löschen (Tage: 0-7)",
            style=TextStyle.short,
            placeholder="0",
            default="0",
            required=False,
            max_length=1
        )
        self.add_item(self.delete_days_input)

    async def on_submit(self, interaction: Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ Server nicht gefunden.", ephemeral=True)
            return

        # Check moderator permissions
        if not interaction.user.guild_permissions.ban_members and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Du hast keine Berechtigung, Mitglieder zu bannen.", ephemeral=True)
            return

        days = 0
        if self.delete_days_input.value and self.delete_days_input.value.strip().isdigit():
            val = int(self.delete_days_input.value.strip())
            days = max(0, min(7, val))

        reason_text = self.reason_input.value.strip() if self.reason_input.value and self.reason_input.value.strip() else "Kein Grund angegeben"
        full_reason = f"Dashboard-Bann durch {interaction.user.display_name}: {reason_text}"

        try:
            await guild.ban(discord.Object(id=self.target_id), reason=full_reason, delete_message_days=days)
            
            embed = Embed(
                title="🔨 User erfolgreich gebannt",
                description=f"**Ziel:** <@{self.target_id}> (`{self.target_name}` / ID: `{self.target_id}`)\n**Moderator:** {interaction.user.mention}\n**Grund:** {reason_text}\n**Nachrichten gelöscht:** {days} Tag(e)",
                color=Color.red(),
                timestamp=datetime.utcnow()
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)

            # Log to Dashboard forum or log channel
            if hasattr(self.cog, 'log_ban_action'):
                await self.cog.log_ban_action(guild, interaction.user, self.target_id, self.target_name, reason_text, days)

        except discord.Forbidden:
            await interaction.response.send_message("❌ Der Bot hat keine Berechtigung, diesen User zu bannen (Hierarchie prüfen).", ephemeral=True)
        except Exception as e:
            logger.error(f"Fehler beim Bannen über Dashboard Modal: {e}")
            await interaction.response.send_message(f"❌ Fehler beim Bannen: {e}", ephemeral=True)


class DashboardIdBanModal(discord.ui.Modal):
    def __init__(self, cog_instance: commands.Cog):
        super().__init__(title="User per ID bannen")
        self.cog = cog_instance

        self.user_id_input = discord.ui.TextInput(
            label="User-ID",
            style=TextStyle.short,
            placeholder="z.B. 123456789012345678",
            required=True,
            max_length=20
        )
        self.add_item(self.user_id_input)

        self.reason_input = discord.ui.TextInput(
            label="Bann-Grund",
            style=TextStyle.long,
            placeholder="Grund für den Bann...",
            required=False,
            max_length=500
        )
        self.add_item(self.reason_input)

        self.delete_days_input = discord.ui.TextInput(
            label="Nachrichten löschen (Tage: 0-7)",
            style=TextStyle.short,
            placeholder="0",
            default="0",
            required=False,
            max_length=1
        )
        self.add_item(self.delete_days_input)

    async def on_submit(self, interaction: Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ Server nicht gefunden.", ephemeral=True)
            return

        if not interaction.user.guild_permissions.ban_members and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Du hast keine Berechtigung, Mitglieder zu bannen.", ephemeral=True)
            return

        raw_id = self.user_id_input.value.strip()
        if not raw_id.isdigit():
            await interaction.response.send_message("❌ Ungültige User-ID. Bitte eine numerische ID eingeben.", ephemeral=True)
            return

        target_id = int(raw_id)
        if target_id == interaction.user.id:
            await interaction.response.send_message("❌ Du kannst dich nicht selbst bannen.", ephemeral=True)
            return
        if target_id == guild.me.id:
            await interaction.response.send_message("❌ Ich kann mich nicht selbst bannen.", ephemeral=True)
            return

        days = 0
        if self.delete_days_input.value and self.delete_days_input.value.strip().isdigit():
            val = int(self.delete_days_input.value.strip())
            days = max(0, min(7, val))

        reason_text = self.reason_input.value.strip() if self.reason_input.value and self.reason_input.value.strip() else "Kein Grund angegeben"
        full_reason = f"Dashboard-ID-Bann durch {interaction.user.display_name}: {reason_text}"

        try:
            await guild.ban(discord.Object(id=target_id), reason=full_reason, delete_message_days=days)
            
            embed = Embed(
                title="🔨 User per ID erfolgreich gebannt",
                description=f"**Ziel-ID:** <@{target_id}> (`{target_id}`)\n**Moderator:** {interaction.user.mention}\n**Grund:** {reason_text}\n**Nachrichten gelöscht:** {days} Tag(e)",
                color=Color.red(),
                timestamp=datetime.utcnow()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

            if hasattr(self.cog, 'log_ban_action'):
                await self.cog.log_ban_action(guild, interaction.user, target_id, f"ID: {target_id}", reason_text, days)

        except discord.Forbidden:
            await interaction.response.send_message("❌ Der Bot hat keine Berechtigung, diese User-ID zu bannen.", ephemeral=True)
        except Exception as e:
            logger.error(f"Fehler beim ID-Bann: {e}")
            await interaction.response.send_message(f"❌ Fehler beim Bannen: {e}", ephemeral=True)


# --- UI VIEWS ---

class DashboardUserSelect(discord.ui.UserSelect):
    def __init__(self, cog_instance: Optional[commands.Cog] = None):
        super().__init__(
            placeholder="🔍 Mitglied zum Bannen auswählen/suchen...",
            min_values=1,
            max_values=1,
            custom_id="dashboard_ban_user_select"
        )
        self.cog = cog_instance

    async def callback(self, interaction: Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ Server nicht gefunden.", ephemeral=True)
            return

        # Check moderator permissions
        if not interaction.user.guild_permissions.ban_members and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Du hast keine Berechtigung, Mitglieder zu bannen.", ephemeral=True)
            return

        # Extract selected user
        target_id = None
        target_name = "Unbekannter User"

        if self.values:
            val = self.values[0]
            if isinstance(val, (discord.User, discord.Member)):
                target_id = val.id
                target_name = val.display_name or val.name
            elif hasattr(val, 'id'):
                target_id = val.id
                target_name = str(val)

        if not target_id:
            raw_vals = interaction.data.get('values', [])
            if raw_vals and raw_vals[0].isdigit():
                target_id = int(raw_vals[0])

        if not target_id:
            await interaction.response.send_message("❌ Kein User ausgewählt.", ephemeral=True)
            return

        # Hierarchy & self-checks
        if target_id == interaction.user.id:
            await interaction.response.send_message("❌ Du kannst dich nicht selbst bannen.", ephemeral=True)
            return

        if target_id == guild.me.id:
            await interaction.response.send_message("❌ Ich kann mich nicht selbst bannen.", ephemeral=True)
            return

        member = guild.get_member(target_id)
        if member:
            target_name = member.display_name
            # Check hierarchy
            if member.top_role >= interaction.user.top_role and guild.owner_id != interaction.user.id:
                await interaction.response.send_message("❌ Du kannst keine Mitglieder bannen, deren höchste Rolle höher oder gleich deiner eigenen ist.", ephemeral=True)
                return

        cog = self.cog or interaction.client.get_cog("Dashboard")
        modal = DashboardBanModal(target_id=target_id, target_name=target_name, cog_instance=cog)
        await interaction.response.send_modal(modal)


class DashboardIdBanButton(discord.ui.Button):
    def __init__(self, cog_instance: Optional[commands.Cog] = None):
        super().__init__(
            label="User-ID Bannen",
            style=ButtonStyle.danger,
            emoji="🔨",
            custom_id="dashboard_ban_id_button"
        )
        self.cog = cog_instance

    async def callback(self, interaction: Interaction):
        if not interaction.user.guild_permissions.ban_members and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Du hast keine Berechtigung, Mitglieder zu bannen.", ephemeral=True)
            return

        cog = self.cog or interaction.client.get_cog("Dashboard")
        modal = DashboardIdBanModal(cog_instance=cog)
        await interaction.response.send_modal(modal)


class DashboardBanView(discord.ui.View):
    def __init__(self, cog_instance: Optional[commands.Cog] = None):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.add_item(DashboardUserSelect(cog_instance))
        self.add_item(DashboardIdBanButton(cog_instance))


# --- STREAMER MANAGEMENT VIEWS & MODALS ---

class DashboardTwitchAddModal(discord.ui.Modal):
    def __init__(self, cog_instance: Optional[commands.Cog] = None):
        super().__init__(title="Twitch-Streamer zum Feed hinzufügen")
        self.cog = cog_instance

        self.twitch_user_input = discord.ui.TextInput(
            label="Twitch Benutzername / URL",
            style=TextStyle.short,
            placeholder="z.B. montanablack oder twitch.tv/trymacs",
            required=True,
            max_length=100
        )
        self.add_item(self.twitch_user_input)

        self.event_mode_input = discord.ui.TextInput(
            label="Modus (channel_only, event_only, both)",
            style=TextStyle.short,
            placeholder="channel_only",
            default="channel_only",
            required=False,
            max_length=20
        )
        self.add_item(self.event_mode_input)

    async def on_submit(self, interaction: Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ Server nicht gefunden.", ephemeral=True)
            return

        if not interaction.user.guild_permissions.ban_members and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Du hast keine Berechtigung für die Streamer-Verwaltung.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        twitch_user = self.twitch_user_input.value.strip()
        event_mode = self.event_mode_input.value.strip().lower() or "channel_only"

        twitch_cog = interaction.client.get_cog("Twitch-Live-Alert")
        if not twitch_cog:
            await interaction.followup.send("❌ Twitch-Live-Alert Modul ist auf dem Bot nicht geladen.", ephemeral=True)
            return

        dash_config = interaction.client.data.get_guild_data(guild.id, "dashboard_config")
        streamer_role_id = dash_config.get('streamer_role_id')

        success, msg = await twitch_cog.web_set_config(guild.id, twitch_user, streamer_role_id, event_mode)
        await interaction.followup.send(msg, ephemeral=True)

        if success and self.cog and hasattr(self.cog, 'setup_dashboard_forum'):
            await self.cog.setup_dashboard_forum(guild)


class DashboardTwitchRemoveSelect(discord.ui.Select):
    def __init__(self, registered_streamers: dict, cog_instance: Optional[commands.Cog] = None):
        options = []
        for s_key, s_data in registered_streamers.items():
            name = s_data.get('display_name') or s_data.get('twitch_user') or s_key
            options.append(discord.SelectOption(
                label=name[:25],
                value=s_key,
                description=f"twitch.tv/{s_key}"[:50],
                emoji="📺"
            ))

        if not options:
            options.append(discord.SelectOption(label="Keine Streamer vorhanden", value="none"))

        super().__init__(
            placeholder="🗑️ Twitch-Streamer zum Entfernen auswählen...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="dashboard_twitch_remove_select"
        )
        self.cog = cog_instance

    async def callback(self, interaction: Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ Server nicht gefunden.", ephemeral=True)
            return

        if not interaction.user.guild_permissions.ban_members and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Du hast keine Berechtigung.", ephemeral=True)
            return

        if self.values[0] == "none":
            await interaction.response.send_message("Keine gültige Auswahl.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        s_key = self.values[0]

        twitch_cog = interaction.client.get_cog("Twitch-Live-Alert")
        if not twitch_cog:
            await interaction.followup.send("❌ Twitch-Live-Alert Modul ist nicht geladen.", ephemeral=True)
            return

        success, msg = await twitch_cog.web_remove_streamer(guild.id, s_key)
        await interaction.followup.send(msg, ephemeral=True)

        if success and self.cog and hasattr(self.cog, 'setup_dashboard_forum'):
            await self.cog.setup_dashboard_forum(guild)


class DashboardTwitchRemoveView(discord.ui.View):
    def __init__(self, registered_streamers: dict, cog_instance: Optional[commands.Cog] = None):
        super().__init__(timeout=60)
        self.add_item(DashboardTwitchRemoveSelect(registered_streamers, cog_instance))


class StreamerRoleUserSelect(discord.ui.UserSelect):
    def __init__(self, cog_instance: Optional[commands.Cog] = None):
        super().__init__(
            placeholder="👥 Mitglied(er) für Streamer-Rolle auswählen...",
            min_values=1,
            max_values=10,
            custom_id="dashboard_streamer_role_user_select"
        )
        self.cog = cog_instance

    async def callback(self, interaction: Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ Server nicht gefunden.", ephemeral=True)
            return

        if not interaction.user.guild_permissions.ban_members and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Keine Berechtigung für die Streamer-Rollen-Verwaltung.", ephemeral=True)
            return

        dash_config = interaction.client.data.get_guild_data(guild.id, "dashboard_config")
        streamer_role_id = dash_config.get('streamer_role_id')
        if not streamer_role_id:
            await interaction.response.send_message(
                "❌ **Keine Streamer-Rolle konfiguriert.** Bitte wähle zuerst im Web-Dashboard unter *Dashboard-Modul* eine Streamer-Rolle aus.",
                ephemeral=True
            )
            return

        streamer_role = guild.get_role(streamer_role_id)
        if not streamer_role:
            await interaction.response.send_message("❌ Die konfigurierte Streamer-Rolle wurde auf dem Server nicht gefunden.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        added = []
        removed = []
        failed = []

        for val in self.values:
            member = None
            if isinstance(val, discord.Member):
                member = val
            elif hasattr(val, 'id'):
                member = guild.get_member(val.id)

            if not member:
                continue

            try:
                if streamer_role in member.roles:
                    await member.remove_roles(streamer_role, reason="Streamer-Rolle via Dashboard entfernt")
                    removed.append(member.display_name)
                else:
                    await member.add_roles(streamer_role, reason="Streamer-Rolle via Dashboard vergeben")
                    added.append(member.display_name)
            except discord.Forbidden:
                failed.append(f"{member.display_name} (Keine Rechte)")
            except Exception as e:
                failed.append(f"{member.display_name} ({e})")

        msg_parts = []
        if added:
            msg_parts.append(f"✅ Rolle {streamer_role.mention} vergeben an: **{', '.join(added)}**")
        if removed:
            msg_parts.append(f"🗑️ Rolle {streamer_role.mention} entfernt von: **{', '.join(removed)}**")
        if failed:
            msg_parts.append(f"⚠️ Fehlgeschlagen für: {', '.join(failed)}")

        await interaction.followup.send("\n".join(msg_parts) if msg_parts else "Keine Änderungen durchgeführt.", ephemeral=True)

        if (added or removed) and self.cog and hasattr(self.cog, 'setup_dashboard_forum'):
            await self.cog.setup_dashboard_forum(guild)


class DashboardTwitchAddButton(discord.ui.Button):
    def __init__(self, cog_instance: Optional[commands.Cog] = None):
        super().__init__(
            label="➕ Streamer hinzufügen",
            style=ButtonStyle.success,
            emoji="📺",
            custom_id="dashboard_twitch_add_btn"
        )
        self.cog = cog_instance

    async def callback(self, interaction: Interaction):
        await interaction.response.send_modal(DashboardTwitchAddModal(self.cog))


class DashboardTwitchRemoveButton(discord.ui.Button):
    def __init__(self, cog_instance: Optional[commands.Cog] = None):
        super().__init__(
            label="🗑️ Streamer entfernen",
            style=ButtonStyle.danger,
            emoji="🗑️",
            custom_id="dashboard_twitch_remove_btn"
        )
        self.cog = cog_instance

    async def callback(self, interaction: Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ Server nicht gefunden.", ephemeral=True)
            return

        twitch_config = interaction.client.data.get_guild_data(guild.id, "twitch_alerts")
        registered_streamers = twitch_config.get("streamers", {})

        if not registered_streamers:
            await interaction.response.send_message("❌ Keine Twitch-Streamer im Feed registriert.", ephemeral=True)
            return

        view = DashboardTwitchRemoveView(registered_streamers, self.cog)
        await interaction.response.send_message("Wähle einen Streamer aus, der aus dem Feed entfernt werden soll:", view=view, ephemeral=True)


class DashboardStreamerManagementView(discord.ui.View):
    def __init__(self, cog_instance: Optional[commands.Cog] = None):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.add_item(StreamerRoleUserSelect(cog_instance))
        self.add_item(DashboardTwitchAddButton(cog_instance))
        self.add_item(DashboardTwitchRemoveButton(cog_instance))


# --- COG IMPLEMENTATION ---

class DashboardCog(commands.Cog, name="Dashboard"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.loop.create_task(self.restore_persistent_views())

    async def restore_persistent_views(self):
        await self.bot.wait_until_ready()
        self.bot.add_view(DashboardBanView(self))
        self.bot.add_view(DashboardStreamerManagementView(self))
        logger.info("Persistent Dashboard views registered.")

    def _get_config(self, guild_id: int) -> dict:
        return self.bot.data.get_guild_data(guild_id, "dashboard_config")

    def _save_config(self, guild_id: int, data: dict):
        self.bot.data.save_guild_data(guild_id, "dashboard_config", data)

    async def log_ban_action(self, guild: discord.Guild, moderator: discord.User, target_id: int, target_name: str, reason: str, delete_days: int):
        config = self._get_config(guild.id)
        ban_logs = config.setdefault('ban_logs', [])
        ban_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'moderator_id': moderator.id,
            'moderator_name': moderator.display_name,
            'target_id': target_id,
            'target_name': target_name,
            'reason': reason,
            'delete_days': delete_days
        }
        ban_logs.insert(0, ban_entry)
        config['ban_logs'] = ban_logs[:50]
        self._save_config(guild.id, config)

        log_channel_id = config.get('log_channel_id')
        if not log_channel_id:
            general_config = self.bot.data.get_server_config(guild.id)
            log_channel_id = general_config.get('log_channel_id')

        if log_channel_id:
            channel = guild.get_channel(log_channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                embed = Embed(
                    title="🔨 Dashboard Ban Ausgeführt",
                    color=Color.dark_red(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Ziel", value=f"<@{target_id}> (`{target_name}` / `{target_id}`)", inline=True)
                embed.add_field(name="Moderator", value=moderator.mention, inline=True)
                embed.add_field(name="Grund", value=reason, inline=False)
                embed.add_field(name="Gelöschte Nachrichten", value=f"{delete_days} Tage", inline=True)
                try:
                    await channel.send(embed=embed)
                except Exception as e:
                    logger.warning(f"Konnte Log nicht in Kanal {log_channel_id} senden: {e}")

    async def setup_dashboard_forum(self, guild: discord.Guild) -> tuple[bool, str]:
        """Erstellt oder aktualisiert den Dashboard Forum-Kanal mit privatem Zugriff nur für Moderatoren."""
        try:
            config = self._get_config(guild.id)
            forum_channel_id = config.get('forum_channel_id')
            category_id = config.get('category_id')

            # Ziel-Kategorie ermitteln
            target_category = None
            if category_id:
                cat = guild.get_channel(category_id)
                if isinstance(cat, CategoryChannel):
                    target_category = cat

            # Alle bestehenden Dashboard-Foren auf dem Server suchen (nach Name "📌-dashboard" oder gespeicherter ID)
            matching_forums = [
                ch for ch in guild.forums
                if ch.name == "📌-dashboard" or (forum_channel_id and ch.id == forum_channel_id)
            ]

            forum_channel = None
            if forum_channel_id:
                forum_channel = guild.get_channel(forum_channel_id)
                if not isinstance(forum_channel, ForumChannel):
                    forum_channel = None

            # Falls kein valides forum_channel bekannt ist, aber bereits Foren existieren, nimm das erste
            if not forum_channel and matching_forums:
                forum_channel = matching_forums[0]
                config['forum_channel_id'] = forum_channel.id

            # Bereinigungs-Logik: Lösche ALLE überflüssigen/doppelten Dashboard-Foren
            for extra_forum in matching_forums:
                if forum_channel and extra_forum.id != forum_channel.id:
                    try:
                        await extra_forum.delete(reason="Bereinigung doppelter Dashboard-Foren")
                    except Exception:
                        pass

            # Berechtigungs-Overwrites definieren (Standard: für @everyone gesperrt)
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False, send_messages=False),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_channels=True,
                    manage_threads=True,
                    embed_links=True,
                    ban_members=True
                )
            }

            # Moderations-Rollen Zugriff gewähren
            mod_role_ids = config.get('mod_role_ids', [])
            for role in guild.roles:
                if role.id in mod_role_ids or role.permissions.administrator or role.permissions.ban_members or role.permissions.kick_members or role.permissions.manage_guild:
                    overwrites[role] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        create_public_threads=True,
                        send_messages_in_threads=True
                    )

            if not forum_channel or not isinstance(forum_channel, ForumChannel):
                # Neues Forum erstellen (und sicherstellen, dass alte Reste gelöscht sind)
                for old_f in matching_forums:
                    try:
                        await old_f.delete(reason="Ersetze altes Dashboard-Forum")
                    except Exception:
                        pass

                forum_channel = await guild.create_forum(
                    name="📌-dashboard",
                    topic="🔒 Internes Moderations-Dashboard. Nur für Moderatoren sichtbar.",
                    overwrites=overwrites,
                    category=target_category,
                    reason="Dashboard Modul aktiviert"
                )
                config['forum_channel_id'] = forum_channel.id
                config['ban_thread_id'] = None
                config['ban_message_id'] = None
            else:
                # Berechtigungen und Kategorie auf existierendem Forum aktualisieren
                await forum_channel.edit(
                    overwrites=overwrites,
                    category=target_category,
                    reason="Dashboard Berechtigungen/Kategorie aktualisiert"
                )

            # Prüfen ob Bann-Post (Thread) existiert
            thread_id = config.get('ban_thread_id')
            ban_thread = None
            if thread_id:
                ban_thread = forum_channel.get_thread(thread_id)

            embed = Embed(
                title="🔨 Moderations Dashboard – Member Bannen",
                description=(
                    "**Willkommen im Moderations-Dashboard!**\n\n"
                    "Wähle ein Mitglied aus dem untenstehenden **Dropdown-Menü** aus, um es direkt vom Server zu bannen.\n"
                    "💡 *Über die integrierte Discord-Suche im Dropdown kannst du gezielt nach Server-Mitgliedern suchen.*\n\n"
                    "Falls ein User den Server bereits verlassen hat, nutze den Button **🔨 User-ID Bannen**."
                ),
                color=Color.red()
            )
            embed.set_footer(text="L8teBot Dashboard • Nur für Moderatoren")

            if not ban_thread:
                # Post/Thread im Forum-Kanal erstellen
                thread_with_msg = await forum_channel.create_thread(
                    name="🔨 Bannen",
                    embed=embed,
                    view=DashboardBanView(self)
                )
                ban_thread = thread_with_msg.thread
                config['ban_thread_id'] = ban_thread.id
                config['ban_message_id'] = thread_with_msg.message.id

                try:
                    await ban_thread.edit(pinned=True, reason="Dashboard Haupt-Post gepinnt")
                except Exception:
                    pass
            else:
                # Bestehende Nachricht aktualisieren
                msg_id = config.get('ban_message_id')
                if msg_id:
                    try:
                        msg = await ban_thread.fetch_message(msg_id)
                        await msg.edit(embed=embed, view=DashboardBanView(self))
                    except Exception:
                        new_msg = await ban_thread.send(embed=embed, view=DashboardBanView(self))
                        config['ban_message_id'] = new_msg.id

            self._save_config(guild.id, config)

            # Streamer Management Thread im Forum einrichten / aktualisieren
            await self.setup_streamer_management_thread(guild, forum_channel)

            return True, f"Dashboard-Forum ({forum_channel.mention}) erfolgreich erstellt/aktualisiert!"

        except discord.Forbidden:
            return False, "Der Bot hat keine Berechtigungen, Forum-Kanäle zu erstellen oder zu verwalten."
        except Exception as e:
            logger.error(f"Fehler bei setup_dashboard_forum: {e}")
            return False, f"Fehler beim Erstellen des Dashboards: {e}"

    async def setup_streamer_management_thread(self, guild: discord.Guild, forum_channel: ForumChannel):
        """Erstellt oder aktualisiert den Streamer & Twitch-Feed Management Post im Dashboard Forum."""
        try:
            config = self._get_config(guild.id)
            streamer_role_id = config.get('streamer_role_id')
            streamer_role = guild.get_role(streamer_role_id) if streamer_role_id else None

            # Streamer mit Rolle
            role_text = streamer_role.mention if streamer_role else "*Keine Streamer-Rolle konfiguriert*"
            members_with_role = [m for m in guild.members if streamer_role and streamer_role in m.roles]
            if members_with_role:
                member_names = [f"• {m.mention} (`{m.display_name}`)" for m in members_with_role[:20]]
                if len(members_with_role) > 20:
                    member_names.append(f"*... und {len(members_with_role) - 20} weitere*")
                members_text = "\n".join(member_names)
            else:
                members_text = "Keine Mitglieder haben aktuell die Streamer-Rolle."

            # Registrierte Twitch-Alert Streamer
            twitch_config = self.bot.data.get_guild_data(guild.id, "twitch_alerts")
            registered_streamers = twitch_config.get("streamers", {})
            if registered_streamers:
                streamer_list = []
                for s_key, s_data in registered_streamers.items():
                    name = s_data.get('display_name') or s_data.get('twitch_user') or s_key
                    is_live = s_data.get('is_live', False)
                    status_str = "🔴 LIVE" if is_live else "⚫ OFFLINE"
                    streamer_list.append(f"• **{name}** (`{s_key}`) – {status_str}")
                twitch_text = "\n".join(streamer_list)
            else:
                twitch_text = "Keine Twitch-Streamer im Live-Alert Feed eingerichtet."

            embed = Embed(
                title="📺 Streamer & Twitch-Feed Management",
                description=(
                    "Verwalte hier die **Streamer-Rolle** deiner Server-Mitglieder und die **Twitch-Live-Alerts**.\n\n"
                    "👥 **Streamer-Rollen-Verwaltung:**\n"
                    "Wähle Mitglieder aus dem **Dropdown-Menü** unten, um ihnen die Streamer-Rolle zu geben oder zu entziehen.\n\n"
                    "📡 **Twitch-Feed Steuerung:**\n"
                    "Nutze die Buttons **➕ Streamer hinzufügen** oder **🗑️ Streamer entfernen**, um Twitch-Accounts direkt im Live-Alert zu verwalten."
                ),
                color=Color.purple()
            )
            embed.add_field(name=f"🎥 Streamer-Rolle ({role_text})", value=members_text, inline=False)
            embed.add_field(name="📡 Twitch Live-Feed Streamer", value=twitch_text, inline=False)
            embed.set_footer(text="L8teBot Streamer Management • Nur für Moderatoren")

            thread_id = config.get('streamer_thread_id')
            streamer_thread = None
            if thread_id:
                streamer_thread = forum_channel.get_thread(thread_id)

            if not streamer_thread:
                thread_with_msg = await forum_channel.create_thread(
                    name="📺 Streamer-Management",
                    embed=embed,
                    view=DashboardStreamerManagementView(self)
                )
                streamer_thread = thread_with_msg.thread
                config['streamer_thread_id'] = streamer_thread.id
                config['streamer_message_id'] = thread_with_msg.message.id
                try:
                    await streamer_thread.edit(pinned=True, reason="Streamer Management Post gepinnt")
                except Exception:
                    pass
            else:
                msg_id = config.get('streamer_message_id')
                if msg_id:
                    try:
                        msg = await streamer_thread.fetch_message(msg_id)
                        await msg.edit(embed=embed, view=DashboardStreamerManagementView(self))
                    except Exception:
                        new_msg = await streamer_thread.send(embed=embed, view=DashboardStreamerManagementView(self))
                        config['streamer_message_id'] = new_msg.id

            self._save_config(guild.id, config)
        except Exception as e:
            logger.error(f"Fehler bei setup_streamer_management_thread: {e}")

    # --- Slash Commands ---
    @app_commands.command(name="dashboard_setup", description="Erstellt oder aktualisiert das Moderations-Dashboard Forum.")
    @app_commands.checks.has_permissions(administrator=True)
    async def dashboard_setup_cmd(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        success, msg = await self.setup_dashboard_forum(interaction.guild)
        await interaction.followup.send(msg, ephemeral=True)

    # --- Web Integration Methods ---
    async def web_on_enable(self, guild_id: int) -> tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return False, "Server nicht gefunden."
        return await self.setup_dashboard_forum(guild)

    async def web_on_disable(self, guild_id: int) -> tuple[bool, str]:
        config = self._get_config(guild_id)
        forum_id = config.get('forum_channel_id')
        if forum_id:
            guild = self.bot.get_guild(guild_id)
            if guild:
                channel = guild.get_channel(forum_id)
                if channel:
                    try:
                        await channel.delete(reason="Dashboard Modul deaktiviert")
                        config['forum_channel_id'] = None
                        config['ban_thread_id'] = None
                        config['ban_message_id'] = None
                        config['streamer_thread_id'] = None
                        config['streamer_message_id'] = None
                        self._save_config(guild_id, config)
                    except Exception:
                        pass
        return True, "Dashboard Modul deaktiviert."

    async def web_set_config(self, guild_id: int, mod_role_ids: list, log_channel_id: Optional[int], category_id: Optional[int] = None, streamer_role_id: Optional[int] = None) -> tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return False, "Server nicht gefunden."

        config = self._get_config(guild_id)
        config['mod_role_ids'] = mod_role_ids
        config['log_channel_id'] = log_channel_id
        config['category_id'] = category_id
        config['streamer_role_id'] = streamer_role_id
        self._save_config(guild_id, config)

        await self.setup_dashboard_forum(guild)
        return True, "Dashboard Einstellungen gespeichert und Forum aktualisiert!"

async def setup(bot):
    await bot.add_cog(DashboardCog(bot))
