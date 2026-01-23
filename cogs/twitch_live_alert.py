# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
import aiohttp
from typing import Optional, Dict, Any, Tuple
import time
import asyncio
from datetime import datetime, timezone

# --- Discord UI Views (Buttons) ---
class NotificationView(discord.ui.View):
    """
    Eine persistente View mit einem Link-Button zum Stream und einem Toggle-Button für Benachrichtigungen.
    """
    def __init__(self, streamer_url: str):
        super().__init__(timeout=None)
        stream_button = discord.ui.Button(label="Stream anschauen", style=discord.ButtonStyle.link, url=streamer_url, emoji="📺")
        self.add_item(stream_button)
        self.add_item(discord.ui.Button(label="Benachrichtigung an/aus", style=discord.ButtonStyle.secondary, custom_id="twitch_alert_toggle_notification", emoji="🔔"))

    @staticmethod
    async def toggle_notification_role(interaction: discord.Interaction):
        """Statische Methode, die die Benachrichtigungsrolle für einen Benutzer umschaltet."""
        await interaction.response.defer(ephemeral=True, thinking=True)
        cog = interaction.client.get_cog("Twitch-Live-Alert")
        if not cog:
            return await interaction.followup.send("Fehler: Das Twitch-Modul ist derzeit nicht verfügbar.", ephemeral=True)

        # Wir müssen herausfinden, welche Rolle der User will.
        # Da wir mehrere Streamer unterstützen, prüfen wir alle konfigurierten Rollen für diesen Server.
        status_config = cog.bot.data.get_guild_data(interaction.guild.id, "twitch_alerts")
        streamers = status_config.get("streamers", {})
        
        # Finde Rolle basierend auf der Nachricht? Schwierig.
        # Einfacher: Die Button-Interaktion gibt uns die Message. Wir suchen den Streamer, der diese Message-ID hat.
        target_streamer = None
        for s_key, s_data in streamers.items():
            if s_data.get("message_id") == interaction.message.id:
                target_streamer = s_data
                break
        
        if not target_streamer:
            # Fallback: Wenn wir nichts finden, schauen wir ob es nur einen gibt (Abwärtskompatibilität)
            if not streamers and status_config.get("message_id") == interaction.message.id:
                 target_streamer = status_config
            else:
                 return await interaction.followup.send("Fehler: Konnte den zugehörigen Streamer nicht identifizieren.", ephemeral=True)

        role_id = target_streamer.get("role_id")
        if not role_id:
            return await interaction.followup.send("Für diesen Streamer ist keine Benachrichtigungs-Rolle konfiguriert.", ephemeral=True)
        
        role = interaction.guild.get_role(role_id)
        if not role:
            return await interaction.followup.send("Die konfigurierte Rolle konnte nicht gefunden werden.", ephemeral=True)

        try:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role, reason="Twitch-Benachrichtigung deaktiviert")
                await interaction.followup.send(f"Du hast die Benachrichtigungen für `{target_streamer.get('display_name', 'diesen Streamer')}` (**{role.name}**) **deaktiviert**.", ephemeral=True)
            else:
                await interaction.user.add_roles(role, reason="Twitch-Benachrichtigung aktiviert")
                await interaction.followup.send(f"Du hast die Benachrichtigungen für `{target_streamer.get('display_name', 'diesen Streamer')}` (**{role.name}**) **aktiviert**.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("Fehler: Ich habe nicht die nötigen Rechte, um dir diese Rolle zu geben.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"Ein Discord-API-Fehler ist aufgetreten: {e}", ephemeral=True)

async def on_toggle_button_click(interaction: discord.Interaction):
    if interaction.data.get("custom_id") == "twitch_alert_toggle_notification":
        await NotificationView.toggle_notification_role(interaction)


class TwitchLiveAlertCog(commands.Cog, name="Twitch-Live-Alert"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.TWITCH_CLIENT_ID = self.bot.config.get("TWITCH_CLIENT_ID")
        self.TWITCH_CLIENT_SECRET = self.bot.config.get("TWITCH_CLIENT_SECRET")
        self.twitch_access_token: Optional[str] = None
        self.bot.loop.create_task(self.initialize_cog())
        # Listener für Button-Klick registrieren (falls nicht schon durch setup() geschehen)
        # bot.add_listener(on_toggle_button_click, 'on_interaction')

    async def initialize_cog(self):
        """Initialisiert den Cog, holt den Token und startet den Loop."""
        await self.bot.wait_until_ready()
        if not self.TWITCH_CLIENT_ID or not self.TWITCH_CLIENT_SECRET:
            print("FEHLER: Twitch Client ID/Secret nicht in config.json gefunden. Twitch-Live-Alert wird nicht gestartet.")
            return
            
        await self.get_twitch_access_token()
        if self.twitch_access_token:
            self.bot.add_view(NotificationView("https://twitch.tv/placeholder"))
            
            print("Führe initiale Status-Prüfung für Twitch-Live-Alert durch...")
            await self._run_update_all_guilds()
            self.check_stream_status.start()
        else:
            print("FEHLER: Konnte keinen Twitch Access Token erhalten.")

    def cog_unload(self):
        self.check_stream_status.cancel()

    @staticmethod
    def _format_last_stream_time(iso_timestamp_str: Optional[str]) -> str:
        if not iso_timestamp_str:
            return "Unbekannt"
        try:
            dt_object = datetime.fromisoformat(iso_timestamp_str.replace('Z', '+00:00'))
            unix_timestamp = int(dt_object.timestamp())
            return f"<t:{unix_timestamp}:R>"
        except (ValueError, TypeError):
            return "Unbekannt"

    async def get_twitch_access_token(self):
        url = f"https://id.twitch.tv/oauth2/token?client_id={self.TWITCH_CLIENT_ID}&client_secret={self.TWITCH_CLIENT_SECRET}&grant_type=client_credentials"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        self.twitch_access_token = data['access_token']
                    else:
                        print(f"Fehler beim Holen des Twitch Tokens: {response.status}")
                        self.twitch_access_token = None
        except Exception as e:
            print(f"Netzwerkfehler beim Holen des Twitch Tokens: {e}")

    async def get_stream_info(self, streamer_name: str) -> Optional[Dict[str, Any]]:
        if not self.twitch_access_token:
            await self.get_twitch_access_token()
            if not self.twitch_access_token: return None
        
        headers = {'Client-ID': self.TWITCH_CLIENT_ID, 'Authorization': f'Bearer {self.twitch_access_token}'}
        async with aiohttp.ClientSession(headers=headers) as session:
            try:
                async with session.get(f"https://api.twitch.tv/helix/users?login={streamer_name}") as user_resp:
                    if user_resp.status == 401:
                        await self.get_twitch_access_token()
                        return await self.get_stream_info(streamer_name)
                    if user_resp.status != 200: return None
                    user_data = await user_resp.json()
                    if not user_data.get('data'): return {"status": "NOT_FOUND"}
                
                user = user_data['data'][0]
                user_id = user['id']
                
                async with session.get(f"https://api.twitch.tv/helix/streams?user_id={user_id}") as stream_resp:
                    stream_data_list = (await stream_resp.json()).get('data', [])

                if stream_data_list:
                    return {**user, **stream_data_list[0], "status": "LIVE"}
                else:
                    offline_info = {**user, "status": "OFFLINE", "last_game_name": "N/A", "last_stream_time": None}
                    async with session.get(f"https://api.twitch.tv/helix/channels?broadcaster_id={user_id}") as channel_resp:
                        if channel_resp.status == 200 and (channel_data := (await channel_resp.json()).get('data')):
                            offline_info["last_game_name"] = channel_data[0].get('game_name') or "Keine Kategorie"
                    async with session.get(f"https://api.twitch.tv/helix/videos?user_id={user_id}&type=archive&first=1&sort=time") as video_resp:
                        if video_resp.status == 200 and (video_data := (await video_resp.json()).get('data')):
                            offline_info["last_stream_time"] = video_data[0].get('created_at')
                    return offline_info
            except Exception as e:
                print(f"Fehler bei Twitch API Anfrage für '{streamer_name}': {e}")
                return None

    def _create_live_embed(self, stream_info: Dict[str, Any]) -> discord.Embed:
        twitch_url = f"https://twitch.tv/{stream_info.get('user_login', '')}"
        embed = discord.Embed(title=str(stream_info.get('title', 'Kein Titel')), url=twitch_url, color=discord.Color.purple())
        embed.set_author(name=f"{stream_info.get('user_name', '')} ist jetzt live!", icon_url=stream_info.get('profile_image_url'), url=twitch_url)
        embed.add_field(name="Spiel/Kategorie", value=str(stream_info.get('game_name', 'N/A')), inline=True)
        embed.add_field(name="Zuschauer", value=f"{stream_info.get('viewer_count', '0')} 👁️", inline=True)

        if thumb_template := stream_info.get('thumbnail_url'):
            thumb_url = str(thumb_template).replace('{width}', '1280').replace('{height}', '720')
            embed.set_image(url=f"{thumb_url}?t={int(time.time())}")
        
        embed.set_footer(text=f"Live seit {stream_info.get('started_at', '')}")
        return embed

    def _create_offline_embed(self, stream_info: Dict[str, Any]) -> discord.Embed:
        twitch_url = f"https://twitch.tv/{stream_info.get('login', '')}"
        embed = discord.Embed(description=f"Hallöchen! Mein Name ist {stream_info.get('display_name')} und ich versuche hier regelmäßig zu streamen.", color=discord.Color.dark_grey())
        embed.set_author(name=f"{stream_info.get('login', '')}", icon_url=stream_info.get('profile_image_url'), url=twitch_url)
        
        last_stream_text = self._format_last_stream_time(stream_info.get("last_stream_time"))
        embed.add_field(name="Letzter Stream", value=last_stream_text, inline=True)
        
        last_game = stream_info.get('last_game_name') or "Just Chatting"
        embed.add_field(name="Zuletzt gespielt", value=last_game, inline=True)
        
        # Nutze das neue, vom Script gehostete Bild
        offline_img_url = f"{self.bot.base_url}/static/images/twitch_offline.png"
        embed.set_image(url=offline_img_url)
        return embed

    async def _update_streamer_status(self, guild: discord.Guild, streamer_key: str, s_data: dict, status_config: dict):
        """Aktualisiert den Status für einen Streamer auf einem Server."""
        twitch_user = s_data.get("twitch_user")
        channel_id = s_data.get("channel_id")
        if not twitch_user or not channel_id: return

        stream_info = await self.get_stream_info(twitch_user)
        if not stream_info or stream_info['status'] == 'NOT_FOUND': return

        channel = guild.get_channel(channel_id)
        if not channel: return
        
        is_live = stream_info['status'] == 'LIVE'
        was_live = s_data.get("is_live", False)
        twitch_url = f"https://twitch.tv/{stream_info.get('user_login') or stream_info.get('login')}"
        view = NotificationView(streamer_url=twitch_url)
        
        role = guild.get_role(s_data.get("role_id"))
        ping_content = role.mention if role else ""

        try:
            if is_live:
                # Kanal-Name ändern
                if channel.name != "🔴｜live":
                    try: await channel.edit(name="🔴｜live")
                    except: pass
                
                embed = self._create_live_embed(stream_info)
                
                # Wenn er gerade erst live gegangen ist -> NEUE Nachricht senden für echten PING
                if not was_live:
                    # Alte Nachricht löschen?
                    if msg_id := s_data.get("message_id"):
                        try:
                            old_msg = await channel.fetch_message(msg_id)
                            await old_msg.delete()
                        except: pass
                    
                    msg = await channel.send(content=ping_content, embed=embed, view=view)
                    s_data["message_id"] = msg.id
                    s_data["is_live"] = True
                else:
                    # War schon live -> nur Embed aktualisieren (Zuschauerzahl etc)
                    if msg_id := s_data.get("message_id"):
                        try:
                            msg = await channel.fetch_message(msg_id)
                            await msg.edit(embed=embed, view=view)
                        except:
                            # Falls gelöscht, neu senden
                            msg = await channel.send(content=ping_content, embed=embed, view=view)
                            s_data["message_id"] = msg.id
            else:
                # Kanal-Name ändern
                if channel.name != "⚫｜offline":
                    try: await channel.edit(name="⚫｜offline")
                    except: pass
                
                # Wenn er offline gegangen ist oder wir die Nachricht noch nicht geschickt haben
                if was_live or not s_data.get("message_id"):
                    embed = self._create_offline_embed(stream_info)
                    if msg_id := s_data.get("message_id"):
                        try:
                            msg = await channel.fetch_message(msg_id)
                            await msg.edit(content="", embed=embed, view=view)
                        except:
                            msg = await channel.send(content="", embed=embed, view=view)
                            s_data["message_id"] = msg.id
                    else:
                        msg = await channel.send(content="", embed=embed, view=view)
                        s_data["message_id"] = msg.id
                    s_data["is_live"] = False

        except Exception as e:
            print(f"Fehler im Update für {twitch_user} auf {guild.id}: {e}")

    async def _run_update_all_guilds(self):
        for guild in self.bot.guilds:
            status_config = self.bot.data.get_guild_data(guild.id, "twitch_alerts")
            
            # Migration von Single-Structure zu Multi-Structure (falls nötig)
            if "twitch_user" in status_config and "streamers" not in status_config:
                old_user = status_config["twitch_user"]
                streamers = status_config.setdefault("streamers", {})
                streamers[old_user.lower()] = {
                    "twitch_user": old_user,
                    "channel_id": status_config.get("channel_id"),
                    "role_id": status_config.get("role_id"),
                    "is_live": status_config.get("is_live", False),
                    "message_id": status_config.get("message_id"),
                    "display_name": status_config.get("display_name", old_user)
                }
                # Alte Daten entfernen (optional, aber sauberer)
                keys_to_del = ["twitch_user", "channel_id", "role_id", "is_live", "message_id", "display_name", "profile_image_url"]
                for k in keys_to_del: 
                    if k in status_config: del status_config[k]
                self.bot.data.save_guild_data(guild.id, "twitch_alerts", status_config)

            streamers = status_config.get("streamers", {})
            for s_key, s_data in streamers.items():
                await self._update_streamer_status(guild, s_key, s_data, status_config)
                await asyncio.sleep(1)
            
            if streamers:
                self.bot.data.save_guild_data(guild.id, "twitch_alerts", status_config)

    @tasks.loop(minutes=5)
    async def check_stream_status(self):
        await self._run_update_all_guilds()

    @check_stream_status.before_loop
    async def before_check_stream_status(self):
        await self.bot.wait_until_ready()

    # --- Web-API Methoden ---
    async def web_get_config(self, guild_id: int) -> Dict[str, Any]:
        return self.bot.data.get_guild_data(guild_id, "twitch_alerts")

    async def web_remove_streamer(self, guild_id: int, streamer_key: str) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."
        
        status_config = self.bot.data.get_guild_data(guild_id, "twitch_alerts")
        streamers = status_config.get("streamers", {})
        
        if streamer_key not in streamers:
            return False, "Streamer nicht gefunden."
        
        data = streamers.pop(streamer_key)
        if channel_id := data.get("channel_id"):
            if channel := guild.get_channel(channel_id):
                try: await channel.delete(reason="Twitch Alert entfernt.")
                except: pass

        self.bot.data.save_guild_data(guild_id, "twitch_alerts", status_config)
        return True, "Streamer und zugehöriger Kanal wurden erfolgreich entfernt."

    async def web_set_config(self, guild_id: int, twitch_user: str, role_id: Optional[int]) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."
        
        stream_info = await self.get_stream_info(twitch_user)
        if not stream_info or stream_info.get('status') == 'NOT_FOUND':
            return False, f"Fehler: Twitch-Benutzer `{twitch_user}` wurde nicht gefunden."
        
        status_config = self.bot.data.get_guild_data(guild_id, "twitch_alerts")
        streamers = status_config.setdefault("streamers", {})
        s_key = stream_info['login'].lower()
        
        # Falls es diesen Streamer schon gibt, nutzen wir alten Kanal oder erstellen neu
        existing_data = streamers.get(s_key, {})
        channel_id = existing_data.get("channel_id")
        channel = guild.get_channel(channel_id) if channel_id else None
        
        if not channel:
            overwrites = { 
                guild.default_role: discord.PermissionOverwrite(send_messages=False, read_messages=True), 
                guild.me: discord.PermissionOverwrite(send_messages=True, manage_channels=True, read_messages=True, embed_links=True) 
            }
            try:
                category = discord.utils.get(guild.categories, name="Twitch Status") or await guild.create_category("Twitch Status")
                channel = await guild.create_text_channel(name="⚫｜offline", overwrites=overwrites, category=category, reason="Twitch Alert Setup")
            except discord.Forbidden:
                 return False, "Fehler: Bot hat keine Rechte, einen Kanal zu erstellen."
        
        streamers[s_key] = {
            "twitch_user": stream_info['login'], 
            "display_name": stream_info['display_name'],
            "channel_id": channel.id, 
            "role_id": role_id, 
            "is_live": False, 
            "message_id": None
        }
        self.bot.data.save_guild_data(guild_id, "twitch_alerts", status_config)
        
        # Trigger sofortiges Update für diesen Streamer
        await self._update_streamer_status(guild, s_key, streamers[s_key], status_config)
        self.bot.data.save_guild_data(guild_id, "twitch_alerts", status_config)
            
        return True, f"Twitch-Alert für '{stream_info['display_name']}' wurde in {channel.mention} konfiguriert."

async def setup(bot: commands.Bot):
    cog = TwitchLiveAlertCog(bot)
    await bot.add_cog(cog)
    bot.add_listener(on_toggle_button_click, 'on_interaction')