# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
import datetime
import typing
import secrets
import time

class WrappedView(discord.ui.View):
    def __init__(self, bot: commands.Bot, label="Mein Wrapped anzeigen"):
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(WrappedButton(label=label))

class WrappedButton(discord.ui.Button):
    def __init__(self, label):
        super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id="wrapped_show_button", emoji="🎉")

    async def callback(self, interaction: discord.Interaction):
        # Nutze die Logik aus der Cog Instanz
        cog = interaction.client.get_cog("Wrapped")
        if not cog:
            return await interaction.response.send_message("Fehler: Wrapped-Modul nicht geladen.", ephemeral=True)
        
        # Rufe eine Hilfsmethode im Cog auf, um den Code nicht zu duplizieren
        await cog.send_user_wrapped(interaction)

class WrappedWebLinkView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild_id: int, user_id: int, year: int):
        super().__init__(timeout=300)  # 5 minutes timeout for the button
        self.bot = bot
        self.guild_id = guild_id
        self.user_id = user_id
        self.year = year
        
        # Generate token
        cog = bot.get_cog("Wrapped")
        if cog:
            token = cog.generate_wrapped_web_token(guild_id, user_id, year)
            # Get base URL from guild config, fallback to global config, then localhost
            config = cog._get_config(guild_id)
            base_url = config.get("web_base_url") or bot.config.get("WEB_BASE_URL", "http://localhost:5002")
            
            # Remove trailing slash if present
            if base_url.endswith("/"):
                base_url = base_url[:-1]
                
            url = f"{base_url}/wrapped/{guild_id}/{token}"
            
            # Create button with actual URL
            button = discord.ui.Button(
                label="🌐 Online anschauen",
                style=discord.ButtonStyle.link,
                url=url
            )
            self.add_item(button)

class WrappedCog(commands.Cog, name="Wrapped"):
    """
    Sammelt Statistiken für den Jahresrückblick (Wrapped).
    Funktionen müssen von einem Admin aktiviert werden.
    Unterscheidet zwischen "Datensammlung aktiv" und "Benutzer-Befehle aktiv".
    Features:
    - Live Tracking (Nachrichten, Voice)
    - Snapshot System: Admins erstellen einen statischen Snapshot für den Jahresrückblick.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Temporärer Speicher für Voice-Join-Zeiten: {guild_id: {user_id: timestamp}}
        self.voice_sessions = {}
        # View registrieren für Persistenz
        self.bot.add_view(WrappedView(self.bot))

    def _get_live_data(self, guild_id: int, year: int) -> dict:
        """Hole die aktuell laufenden (live) Daten."""
        return self.bot.data.get_guild_data(guild_id, f"wrapped_{year}")

    def _save_live_data(self, guild_id: int, year: int, data: dict):
        """Speichere die live Daten."""
        self.bot.data.save_guild_data(guild_id, f"wrapped_{year}", data)

    def _get_snapshot_data(self, guild_id: int, year: int) -> dict:
        """Hole die eingefrorenen Snapshot-Daten für den Rückblick."""
        return self.bot.data.get_guild_data(guild_id, f"wrapped_{year}_snapshot")

    def _save_snapshot_data(self, guild_id: int, year: int, data: dict):
        """Speichere den Snapshot."""
        self.bot.data.save_guild_data(guild_id, f"wrapped_{year}_snapshot", data)

    def _get_config(self, guild_id: int) -> dict:
        # Config ist an die Live-Daten geknüpft oder separate Datei?
        # Um es einfach zu halten, speichern wir Config in Live-Daten, kopieren sie aber ggf. nicht.
        year = datetime.datetime.now().year
        data = self._get_live_data(guild_id, year)
        return data.setdefault("config", {
            "user_commands_enabled": False, 
            "wrapped_channel_id": None,
            "web_links_enabled": False,
            "web_base_url": None
        })

    def _save_config(self, guild_id: int, config: dict):
        year = datetime.datetime.now().year
        data = self._get_live_data(guild_id, year)
        data["config"] = config
        self._save_live_data(guild_id, year, data)

    # --- LISTENER (LIVE TRACKING) ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        
        server_config = self.bot.data.get_server_config(message.guild.id)
        if self.qualified_name not in server_config.get('enabled_cogs', []):
            return

        year = datetime.datetime.now().year
        data = self._get_live_data(message.guild.id, year)

        # 1. Server Stats
        server_stats = data.setdefault("server", {
            "total_messages": 0, 
            "top_emojis": {},
            "active_channels": {},
            "total_voice_minutes": 0
        })
        server_stats["total_messages"] += 1
        
        cid = str(message.channel.id)
        server_stats["active_channels"][cid] = server_stats["active_channels"].get(cid, 0) + 1

        import re
        import emoji as emoji_lib
        
        # Emoji-Tracking: Custom Emojis (normal und animiert) + Unicode Emojis
        all_emojis = []
        
        # 1. Custom Discord Emojis (normal: <:name:id>, animiert: <a:name:id>)
        custom_emojis = re.findall(r'<a?:[a-zA-Z0-9_]+:([0-9]+)>', message.content)
        for emoji_id in custom_emojis:
            all_emojis.append(f"custom:{emoji_id}")
        
        # 2. Unicode Emojis (😂, 🔥, ❤️, etc.)
        try:
            unicode_emojis = emoji_lib.distinct_emoji_list(message.content)
            for ue in unicode_emojis:
                all_emojis.append(f"unicode:{ue}")
        except Exception:
            pass  # Falls emoji-Bibliothek fehlt oder Fehler
        
        # Server-Stats aktualisieren
        for emoji_key in all_emojis:
            server_stats["top_emojis"][emoji_key] = server_stats["top_emojis"].get(emoji_key, 0) + 1

        # 2. User Stats
        user_stats = data.setdefault("users", {})
        uid = str(message.author.id)
        u_data = user_stats.setdefault(uid, {
            "total_messages": 0,
            "top_channel": {},
            "top_emojis": {},
            "voice_minutes": 0,
            "top_voice_channel": {} 
        })
        u_data["total_messages"] += 1
        u_data["top_channel"][cid] = u_data["top_channel"].get(cid, 0) + 1
        
        # User-Emoji-Stats aktualisieren
        for emoji_key in all_emojis:
            u_data["top_emojis"][emoji_key] = u_data["top_emojis"].get(emoji_key, 0) + 1
        
        # 3. Interaction Tracking (für Best Buddy)
        # Initialisiere interactions dict wenn nicht vorhanden
        u_data.setdefault("interactions", {})
        
        # Wenn die Nachricht eine Antwort ist, tracke die Interaktion
        if message.reference and message.reference.message_id:
            try:
                # Hole die ursprüngliche Nachricht
                ref_message = await message.channel.fetch_message(message.reference.message_id)
                if ref_message and not ref_message.author.bot and ref_message.author.id != message.author.id:
                    # Reply interaction
                    self._track_interaction(message.guild.id, message.author.id, ref_message.author.id, weight=3)
            except Exception:
                pass

        self._save_live_data(message.guild.id, year, data)
    
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        """Trackt Reaktionen für Best Buddy Feature."""
        if user.bot or not reaction.message.guild:
            return
        
        server_config = self.bot.data.get_server_config(reaction.message.guild.id)
        if self.qualified_name not in server_config.get('enabled_cogs', []):
            return
        
        # Wenn jemand auf eine Nachricht von jemand anderem reagiert
        if reaction.message.author.id != user.id and not reaction.message.author.bot:
            self._track_interaction(reaction.message.guild.id, user.id, reaction.message.author.id, weight=1)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot: return
        guild_id = member.guild.id
        
        server_config = self.bot.data.get_server_config(guild_id)
        if self.qualified_name not in server_config.get('enabled_cogs', []):
            return

        now = datetime.datetime.now(datetime.timezone.utc)
        self.voice_sessions.setdefault(guild_id, {})
        
        if after.channel:
            if before.channel != after.channel:
                if before.channel:
                    self._finalize_voice_session(member, before.channel, now)
                
                # Best Buddy Tracking: Joining a channel with others counts as interaction
                for other_member in after.channel.members:
                    if other_member.id != member.id and not other_member.bot:
                         self._track_interaction(guild_id, member.id, other_member.id, weight=2) # Higher weight for voice
                         self._track_interaction(guild_id, other_member.id, member.id, weight=2)

                self.voice_sessions[guild_id][member.id] = {"start": now, "channel_id": after.channel.id}
        
        elif before.channel and not after.channel:
            self._finalize_voice_session(member, before.channel, now)
            if member.id in self.voice_sessions[guild_id]:
                del self.voice_sessions[guild_id][member.id]

    def _track_interaction(self, guild_id: int, user_id: int, other_user_id: int, weight: int = 1):
        """Helper to track interactions between two users."""
        year = datetime.datetime.now().year
        data = self._get_live_data(guild_id, year)
        
        user_stats = data.setdefault("users", {})
        uid = str(user_id)
        u_data = user_stats.setdefault(uid, {}) # Ensure dict exists

        # Ensure all keys exist (safe init)
        if "interactions" not in u_data: u_data["interactions"] = {}
        
        other_uid = str(other_user_id)
        u_data["interactions"][other_uid] = u_data["interactions"].get(other_uid, 0) + weight
        
        self._save_live_data(guild_id, year, data)

    def _finalize_voice_session(self, member: discord.Member, channel: discord.VoiceChannel, end_time: datetime.datetime):
        guild_id = member.guild.id
        session = self.voice_sessions.get(guild_id, {}).get(member.id)
        
        if session and session.get("channel_id") == channel.id:
            start_time = session["start"]
            duration_minutes = int((end_time - start_time).total_seconds() / 60)
            
            if duration_minutes > 0:
                year = datetime.datetime.now().year
                data = self._get_live_data(guild_id, year)
                
                server_stats = data.setdefault("server", {})
                server_stats["total_voice_minutes"] = server_stats.get("total_voice_minutes", 0) + duration_minutes
                
                user_stats = data.setdefault("users", {})
                uid = str(member.id)
                u_data = user_stats.setdefault(uid, {
                    "total_messages": 0, "top_channel": {}, "top_emojis": {}, 
                    "voice_minutes": 0, "top_voice_channel": {}
                })
                
                u_data["voice_minutes"] = u_data.get("voice_minutes", 0) + duration_minutes
                
                chan_id_str = str(channel.id)
                u_data.setdefault("top_voice_channel", {})
                u_data["top_voice_channel"][chan_id_str] = u_data["top_voice_channel"].get(chan_id_str, 0) + duration_minutes

                self._save_live_data(guild_id, year, data)

    def register_ticket_processed(self, guild_id: int, user_id: int):
        """Registriert ein bearbeitetes Ticket für den User (für Wrapped)."""
        year = datetime.datetime.now().year
        data = self._get_live_data(guild_id, year)
        
        user_stats = data.setdefault("users", {})
        uid = str(user_id)
        u_data = user_stats.setdefault(uid, {
            "total_messages": 0, "top_channel": {}, "top_emojis": {}, 
            "voice_minutes": 0, "top_voice_channel": {}, "interactions": {},
            "tickets_processed": 0
        })
        
        u_data["tickets_processed"] = u_data.get("tickets_processed", 0) + 1
        self._save_live_data(guild_id, year, data)

    # --- DISPLAY LOGIC (SNAPSHOT BASED) ---

    async def send_user_wrapped(self, interaction: discord.Interaction):
        """
        Sendet Wrapped basierend auf SNAPSHOT Date.
        """
        # Checks
        server_config = self.bot.data.get_server_config(interaction.guild.id)
        if self.qualified_name not in server_config.get('enabled_cogs', []):
             return await interaction.response.send_message("Das Wrapped-System ist auf diesem Server nicht aktiviert.", ephemeral=True)
        
        config = self._get_config(interaction.guild.id)
        if not config.get("user_commands_enabled", False):
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message("Der Jahresrückblick wurde noch nicht veröffentlicht! 🤫", ephemeral=True)

        year = datetime.datetime.now().year
        # HIER: Snapshot laden anstatt Live Data!
        data = self._get_snapshot_data(interaction.guild.id, year)
        
        # Fallback: Falls kein Snapshot existiert, aber User Admin ist -> Warnung oder Live Data?
        # User wollte: "immer nur die infos die in diese datai gepseicherzt worden sind dann nutzen"
        if not data:
             if interaction.user.guild_permissions.administrator:
                 return await interaction.response.send_message("⚠️ **Achtung Admin:** Es wurde noch kein Snapshot erstellt! Geh ins Dashboard und klicke auf 'Snapshot erstellen', damit Daten angezeigt werden.", ephemeral=True)
             else:
                 return await interaction.response.send_message("Der Jahresrückblick ist noch nicht fertig vorbereitet (Snapshot fehlt).", ephemeral=True)

        user_data = data.get("users", {}).get(str(interaction.user.id))

        if not user_data:
            return await interaction.response.send_message("Es liegen keine Daten für dich im aktuellen Snapshot vor.", ephemeral=True)

        # Build Embed
        embed = discord.Embed(title=f"🎉 Dein {year} Wrapped - {interaction.user.display_name}", color=discord.Color.gold())
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        
        embed.add_field(name="✉️ Nachrichten", value=f"**{user_data.get('total_messages', 0)}** verschickt", inline=True)
        
        minutes = user_data.get("voice_minutes", 0)
        hours = round(minutes / 60, 1)
        embed.add_field(name="🎙️ Voice-Zeit", value=f"**{hours}** Stunden ({minutes} Min.)", inline=True)
        
        if user_data.get('top_channel'):
            fav_channel_id = max(user_data['top_channel'], key=user_data['top_channel'].get)
            count = user_data['top_channel'][fav_channel_id]
            embed.add_field(name="✍️ Lieblingskanal", value=f"<#{fav_channel_id}> ({count} Nachrichten)", inline=False)

        if user_data.get('top_voice_channel'):
             fav_v_channel_id = max(user_data['top_voice_channel'], key=user_data['top_voice_channel'].get)
             mins = user_data['top_voice_channel'][fav_v_channel_id]
             embed.add_field(name="🔊 Lieblings-Talk", value=f"<#{fav_v_channel_id}> ({mins} Min.)", inline=True)

        if user_data.get('top_emojis'):
             fav_emoji_key = max(user_data['top_emojis'], key=user_data['top_emojis'].get)
             count = user_data['top_emojis'][fav_emoji_key]
             
             # Emoji-String erstellen basierend auf Typ
             if fav_emoji_key.startswith("custom:"):
                 emoji_id = fav_emoji_key.replace("custom:", "")
                 emoji = self.bot.get_emoji(int(emoji_id))
                 emoji_str = str(emoji) if emoji else "❓ (Emoji gelöscht)"
             elif fav_emoji_key.startswith("unicode:"):
                 emoji_str = fav_emoji_key.replace("unicode:", "")
             else:
                 emoji_str = "❓"
             
             embed.add_field(name="❤️ Lieblings-Emoji", value=f"{emoji_str} ({count}x)", inline=True)
        
        # Best Buddy (meiste Interaktionen)
        if user_data.get('interactions'):
            best_buddy_id = max(user_data['interactions'], key=user_data['interactions'].get)
            interaction_count = user_data['interactions'][best_buddy_id]
            embed.add_field(name="👥 Best Buddy", value=f"<@{best_buddy_id}>\n({interaction_count} Interaktionen)", inline=True)
        
        # Streak-Information
        streak_data = self.bot.data.get_guild_data(interaction.guild.id, "streaks")
        user_streak = streak_data.get(str(interaction.user.id), {})
        current_streak = user_streak.get("current_streak", 0)
        
        if current_streak > 0:
            last_date = user_streak.get("last_message_date", "")
            embed.add_field(name="🔥 Aktuelle Streak", value=f"**{current_streak}** Tage\n(seit {last_date})", inline=True)
        
        # Support-Tickets (falls vorhanden)
        tickets_processed = user_data.get("tickets_processed", 0)
        if tickets_processed > 0:
            embed.add_field(name="🎫 Support-Held", value=f"**{tickets_processed}** Tickets bearbeitet", inline=True)
        
        embed.set_footer(text=f"L8teBot Jahresrückblick • Snapshot Stand: {data.get('snapshot_date', 'Unbekannt')}")
        
        # Check if web links are enabled
        web_links_enabled = config.get("web_links_enabled", False)
        
        if web_links_enabled:
            # Create view with button for web link
            view = WrappedWebLinkView(self.bot, interaction.guild.id, interaction.user.id, year)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="wrapped", description="Zeige deinen persönlichen Jahresrückblick (wenn aktiviert).")
    async def wrapped(self, interaction: discord.Interaction):
        await self.send_user_wrapped(interaction)

    @app_commands.command(name="serverwrapped", description="Zeige den Server-Jahresrückblick (wenn aktiviert).")
    async def server_wrapped(self, interaction: discord.Interaction):
        if not interaction.guild: return
        
        config = self._get_config(interaction.guild.id)
        if not config.get("user_commands_enabled", False):
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message("Der Jahresrückblick wurde noch nicht veröffentlicht! 🤫", ephemeral=True)
        
        year = datetime.datetime.now().year
        # HIER: Snapshot laden
        data = self._get_snapshot_data(interaction.guild.id, year)
        
        if not data:
             return await interaction.response.send_message("Es wurde noch kein Snapshot erstellt. (Admins müssen dies im Dashboard tun)", ephemeral=True)
        
        server_stats = data.get("server", {})

        embed = discord.Embed(title=f"📊 {interaction.guild.name} {year} Wrapped", color=discord.Color.purple())
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        
        embed.add_field(name="✉️ Gesamt-Nachrichten", value=f"**{server_stats.get('total_messages', 0)}**", inline=True)
        
        hours = round(server_stats.get("total_voice_minutes", 0) / 60, 1)
        embed.add_field(name="🎙️ Gesamt-Voice-Zeit", value=f"**{hours}** Stunden", inline=True)
        
        embed.add_field(name="\u200b", value="\u200b", inline=False) 

        users_data = data.get("users", {})
        if users_data:
            top_msg_user_id = max(users_data, key=lambda x: users_data[x].get('total_messages', 0))
            top_msg_count = users_data[top_msg_user_id].get('total_messages', 0)
            embed.add_field(name="✍️ Schreibwütigster", value=f"<@{top_msg_user_id}>\n{top_msg_count} Nachrichten", inline=True)

            top_voice_user_id = max(users_data, key=lambda x: users_data[x].get('voice_minutes', 0))
            top_voice_mins = users_data[top_voice_user_id].get('voice_minutes', 0)
            embed.add_field(name="🦜 Quasselstrippe", value=f"<@{top_voice_user_id}>\n{round(top_voice_mins/60, 1)} Stunden", inline=True)

        if server_stats.get('active_channels'):
            top_channel_id = max(server_stats['active_channels'], key=server_stats['active_channels'].get)
            embed.add_field(name="#️⃣ Aktivster Kanal", value=f"<#{top_channel_id}>", inline=False)

        if server_stats.get('top_emojis'):
             top_emoji_key = max(server_stats['top_emojis'], key=server_stats['top_emojis'].get)
             
             # Emoji-String erstellen basierend auf Typ
             if top_emoji_key.startswith("custom:"):
                 emoji_id = top_emoji_key.replace("custom:", "")
                 emoji = self.bot.get_emoji(int(emoji_id))
                 emoji_str = str(emoji) if emoji else "❓ (Emoji gelöscht)"
             elif top_emoji_key.startswith("unicode:"):
                 emoji_str = top_emoji_key.replace("unicode:", "")
             else:
                 emoji_str = "❓"
             
             embed.add_field(name="😍 Beliebtestes Emoji", value=f"{emoji_str}", inline=True)
        
        # Längste Streak auf dem Server
        streak_data = self.bot.data.get_guild_data(interaction.guild.id, "streaks")
        if streak_data:
            # Finde User mit längster Streak
            longest_streak_user = None
            longest_streak_count = 0
            for user_id_str, user_streak in streak_data.items():
                if user_id_str.isdigit():
                    current = user_streak.get("current_streak", 0)
                    if current > longest_streak_count:
                        longest_streak_count = current
                        longest_streak_user = user_id_str
            
            if longest_streak_user and longest_streak_count > 0:
                embed.add_field(name="🔥 Längste Flamme", value=f"<@{longest_streak_user}>\n**{longest_streak_count}** Tage Streak", inline=True)
        
        embed.set_footer(text=f"Snapshot Stand: {data.get('snapshot_date', 'Unbekannt')}")
        await interaction.response.send_message(embed=embed)

    # --- Web API ---
    async def web_get_config(self, guild_id: int) -> dict:
        return self._get_config(guild_id)
    
    async def web_get_snapshot_info(self, guild_id: int) -> dict:
        """Gibt Infos über den aktuellen Snapshot zurück (Datum, Stats)."""
        year = datetime.datetime.now().year
        data = self._get_snapshot_data(guild_id, year)
        if not data: return None
        return {
            "date": data.get("snapshot_date"),
            "server_stats": data.get("server", {})
        }
    
    async def web_get_live_stats(self, guild_id: int) -> dict:
        """Gibt aktuelle Live-Stats zurück."""
        year = datetime.datetime.now().year
        data = self._get_live_data(guild_id, year)
        return data.get("server", {}) if data else {}

    async def web_create_snapshot(self, guild_id: int) -> tuple:
        """Erstellt eine Kopie der Live-Daten als Snapshot."""
        year = datetime.datetime.now().year
        live_data = self._get_live_data(guild_id, year)
        
        if not live_data:
            # Init empty data if nothing exists yet
            live_data = {"server": {}, "users": {}}
        
        # Add Snapshot Timestamp
        snapshot_data = live_data.copy()
        snapshot_data["snapshot_date"] = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
        
        self._save_snapshot_data(guild_id, year, snapshot_data)
        
        return True, f"Snapshot erfolgreich erstellt! ({snapshot_data['snapshot_date']})"

    async def web_set_command_status(self, guild_id: int, enabled: bool) -> tuple:
        config = self._get_config(guild_id)
        config["user_commands_enabled"] = enabled
        self._save_config(guild_id, config)
        status = "aktiviert" if enabled else "deaktiviert"
        return True, f"Benutzer-Befehle wurden erfolgreich {status}."

    async def web_send_wrapped_button(self, guild_id: int, channel_id: int, text: str = "Schau dir jetzt deinen persönlichen Jahresrückblick an!") -> tuple:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."
        channel = guild.get_channel(channel_id)
        if not channel: return False, "Kanal nicht gefunden."

        config = self._get_config(guild_id)
        config["wrapped_channel_id"] = channel_id
        self._save_config(guild_id, config)

        try:
            embed = discord.Embed(
                title=f"🎉 {datetime.datetime.now().year} Wrapped", 
                description=text,
                color=discord.Color.gold()
            )
            embed.set_footer(text="Klicke auf den Button, um deine Statistiken zu sehen (Snapshot).")
            await channel.send(embed=embed, view=WrappedView(self.bot))
            return True, f"Wrapped-Button erfolgreich in {channel.mention} gesendet."
        except discord.Forbidden:
            return False, "Der Bot hat keine Berechtigung, in diesem Kanal zu schreiben."
        except Exception as e:
            return False, f"Ein Fehler ist aufgetreten: {e}"
    
    async def web_toggle_web_links(self, guild_id: int, enabled: bool) -> tuple:
        """Aktiviert/Deaktiviert die Web-Link-Funktion für Wrapped."""
        config = self._get_config(guild_id)
        config["web_links_enabled"] = enabled
        self._save_config(guild_id, config)
        status = "aktiviert" if enabled else "deaktiviert"
        return True, f"Web-Links für Wrapped wurden {status}."
    
    async def web_set_base_url(self, guild_id: int, url: str) -> tuple:
        """Setzt die Base-URL für die Web-Ansicht (per Guild)."""
        config = self._get_config(guild_id)
        
        # Validation: basic http/https check
        if url and not (url.startswith("http://") or url.startswith("https://")):
            return False, "Die URL muss mit http:// oder https:// beginnen."
            
        config["web_base_url"] = url if url else None
        self._save_config(guild_id, config)
        return True, "Base-URL für Web-Links erfolgreich aktualisiert."
    
    def generate_wrapped_web_token(self, guild_id: int, user_id: int, year: int) -> str:
        """Generiert einen sicheren, zeitlich begrenzten Token für Wrapped Web-Ansicht."""
        # Generate secure random token (64 characters)
        token = secrets.token_urlsafe(48)  # ~64 chars
        
        # Store token with expiry (30 minutes)
        web_tokens = self.bot.data.get_guild_data(guild_id, "wrapped_web_tokens")
        if not web_tokens:
            web_tokens = {}
        
        web_tokens[token] = {
            "user_id": user_id,
            "year": year,
            "created_at": time.time(),
            "expires_at": time.time() + 1800  # 30 minutes
        }
        
        self.bot.data.save_guild_data(guild_id, "wrapped_web_tokens", web_tokens)
        return token
    
    def validate_wrapped_web_token(self, guild_id: int, token: str) -> dict:
        """Validiert einen Wrapped Web-Token und gibt die Daten zurück."""
        web_tokens = self.bot.data.get_guild_data(guild_id, "wrapped_web_tokens")
        if not web_tokens or token not in web_tokens:
            return None
        
        token_data = web_tokens[token]
        
        # Check if expired
        if time.time() > token_data["expires_at"]:
            # Clean up expired token
            del web_tokens[token]
            self.bot.data.save_guild_data(guild_id, "wrapped_web_tokens", web_tokens)
            return None
        
        return token_data

async def setup(bot: commands.Bot):
    await bot.add_cog(WrappedCog(bot))
