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

        status_config = cog.bot.data.get_guild_data(interaction.guild.id, "twitch_alerts")
        role_id = status_config.get("role_id")

        if not role_id:
            return await interaction.followup.send("Für dieses Modul ist keine Benachrichtigungs-Rolle konfiguriert.", ephemeral=True)
        
        role = interaction.guild.get_role(role_id)
        if not role:
            return await interaction.followup.send("Die konfigurierte Rolle konnte nicht gefunden werden. Möglicherweise wurde sie gelöscht.", ephemeral=True)

        try:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role, reason="Twitch-Benachrichtigung deaktiviert")
                await interaction.followup.send(f"Du hast die Benachrichtigungen (`{role.name}`) **deaktiviert**.", ephemeral=True)
            else:
                await interaction.user.add_roles(role, reason="Twitch-Benachrichtigung aktiviert")
                await interaction.followup.send(f"Du hast die Benachrichtigungen (`{role.name}`) **aktiviert**.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("Fehler: Ich habe nicht die nötigen Rechte, um dir diese Rolle zu geben oder zu nehmen.", ephemeral=True)
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
        bot.add_listener(on_toggle_button_click, 'on_interaction')

    async def initialize_cog(self):
        """Initialisiert den Cog, holt den Token, führt ein erstes Update aus und startet den Loop."""
        await self.bot.wait_until_ready()
        if not self.TWITCH_CLIENT_ID or not self.TWITCH_CLIENT_SECRET:
            print("FEHLER: Twitch Client ID/Secret nicht in config.json gefunden. Twitch-Live-Alert wird nicht gestartet.")
            return
            
        await self.get_twitch_access_token()
        if self.twitch_access_token:
            self.bot.add_view(NotificationView("https://twitch.tv/placeholder"))
            
            print("Führe initiale Status-Prüfung nach Neustart durch...")
            try:
                # Iterate over guilds
                tasks = []
                for guild in self.bot.guilds:
                    # using twitch_alerts module
                    status_config = self.bot.data.get_guild_data(guild.id, "twitch_alerts")
                    if status_config and status_config.get("twitch_user"):
                         tasks.append(self._update_guild_status(guild, status_config))
                
                if tasks:
                    await asyncio.gather(*tasks)
                print("Initiale Status-Prüfung abgeschlossen.")
            except Exception as e:
                print(f"Fehler während der initialen Status-Prüfung: {e}")

            self.check_stream_status.start()
            print("Regulärer 5-Minuten-Loop für Twitch-Status gestartet.")
        else:
            print("FEHLER: Konnte keinen Twitch Access Token erhalten. Der Twitch-Live-Alert-Loop wird nicht gestartet.")

    def cog_unload(self):
        self.check_stream_status.cancel()

    @staticmethod
    def _format_last_stream_time(iso_timestamp_str: Optional[str]) -> str:
        """Formatiert einen ISO 8601 Zeitstempel in einen relativen, dynamischen Discord-Timestamp."""
        if not iso_timestamp_str:
            return "Unbekannt"
        try:
            dt_object = datetime.fromisoformat(iso_timestamp_str.replace('Z', '+00:00'))
            unix_timestamp = int(dt_object.timestamp())
            return f"<t:{unix_timestamp}:R>"
        except (ValueError, TypeError):
            return "Unbekannt"

    async def get_twitch_access_token(self):
        """Holt einen neuen App Access Token von Twitch."""
        url = f"https://id.twitch.tv/oauth2/token?client_id={self.TWITCH_CLIENT_ID}&client_secret={self.TWITCH_CLIENT_SECRET}&grant_type=client_credentials"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        self.twitch_access_token = data['access_token']
                        print("Neuen Twitch Access Token erhalten.")
                    else:
                        print(f"Fehler beim Holen des Twitch Tokens: {response.status} - {await response.text()}")
                        self.twitch_access_token = None
        except Exception as e:
            print(f"Netzwerkfehler beim Holen des Twitch Tokens: {e}")

    async def get_stream_info(self, streamer_name: str) -> Optional[Dict[str, Any]]:
        """Holt Stream-, User- und Kanal-Informationen von der Twitch API."""
        if not self.twitch_access_token:
            await self.get_twitch_access_token()
            if not self.twitch_access_token: return None
        
        headers = {'Client-ID': self.TWITCH_CLIENT_ID, 'Authorization': f'Bearer {self.twitch_access_token}'}
        async with aiohttp.ClientSession(headers=headers) as session:
            try:
                async with session.get(f"https://api.twitch.tv/helix/users?login={streamer_name}") as user_resp:
                    if user_resp.status == 401:
                        print("Twitch Token abgelaufen. Fordere einen neuen an.")
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
        embed.set_image(url="https://L8teNever.de/images/Offline-Stream.png")
        return embed

    async def _update_guild_status(self, guild: discord.Guild, status_config: dict):
        """Kernfunktion, die den Status für einen einzelnen Server prüft und aktualisiert."""
        if not status_config.get("twitch_user") or not status_config.get("channel_id"): return

        stream_info = await self.get_stream_info(status_config["twitch_user"])
        if not stream_info: return
        if stream_info['status'] == 'NOT_FOUND': return

        channel = guild.get_channel(status_config["channel_id"])
        if not channel: return
        
        is_live = stream_info['status'] == 'LIVE'
        was_live = status_config.get("is_live", False)

        status_config["is_live"] = is_live
        twitch_url = f"https://twitch.tv/{stream_info.get('user_login') or stream_info.get('login')}"
        view = NotificationView(streamer_url=twitch_url)
        ping_content = ""
        embed = None
        
        save_needed = True

        try:
            if is_live:
                if channel.name != "🔴｜live":
                    await channel.edit(name="🔴｜live")
                embed = self._create_live_embed(stream_info)
                if not was_live and (role_id := status_config.get("role_id")):
                    if role := guild.get_role(role_id):
                        ping_content = role.mention
            else:
                if channel.name != "⚫｜offline":
                    await channel.edit(name="⚫｜offline")
                embed = self._create_offline_embed(stream_info)

            if msg_id := status_config.get("message_id"):
                try:
                    msg = await channel.fetch_message(msg_id)
                    await msg.edit(content=ping_content if is_live and not was_live else "", embed=embed, view=view)
                except (discord.NotFound, discord.Forbidden):
                    status_config["message_id"] = None

            if not status_config.get("message_id"):
                msg = await channel.send(content=ping_content, embed=embed, view=view)
                status_config["message_id"] = msg.id
        except Exception as e:
            print(f"Fehler im Update-Loop für Server {guild.id}: {e}")
            
        return save_needed

    @tasks.loop(minutes=5)
    async def check_stream_status(self):
        """Haupt-Loop, der alle 5 Minuten für alle konfigurierten Server den Status prüft."""
        for guild in self.bot.guilds:
            status_config = self.bot.data.get_guild_data(guild.id, "twitch_alerts")
            if status_config and status_config.get("twitch_user"):
                await self._update_guild_status(guild, status_config)
                self.bot.data.save_guild_data(guild.id, "twitch_alerts", status_config)

    @check_stream_status.before_loop
    async def before_check_stream_status(self):
        await self.bot.wait_until_ready()

    # --- Web-API Methoden (unverändert) ---
    async def web_get_config(self, guild_id: int) -> Dict[str, Any]:
        return self.bot.data.get_guild_data(guild_id, "twitch_alerts")

    async def web_reset_config(self, guild_id: int) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."
        
        status_config = self.bot.data.get_guild_data(guild_id, "twitch_alerts")
        if not status_config:
             return True, "Es war keine Konfiguration zum Zurücksetzen vorhanden."

        if channel_id := status_config.get("channel_id"):
            if channel := guild.get_channel(channel_id):
                try: await channel.delete(reason="Twitch Live Alert Konfiguration zurückgesetzt.")
                except Exception as e: print(f"Konnte Kanal {channel_id} nicht löschen: {e}")

        # Clear config
        self.bot.data.save_guild_data(guild_id, "twitch_alerts", {})
        return True, "Die Konfiguration wurde erfolgreich zurückgesetzt und der zugehörige Kanal gelöscht."

    async def web_set_config(self, guild_id: int, twitch_user: str, role_id: Optional[int]) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."
        
        stream_info = await self.get_stream_info(twitch_user)
        if not stream_info or stream_info.get('status') == 'NOT_FOUND':
            return False, f"Fehler: Twitch-Benutzer `{twitch_user}` wurde nicht gefunden."
        
        status_config = self.bot.data.get_guild_data(guild_id, "twitch_alerts")
        
        channel_id = status_config.get("channel_id")
        channel = guild.get_channel(channel_id) if channel_id else None
        
        if not channel:
            overwrites = { guild.default_role: discord.PermissionOverwrite(send_messages=False, read_messages=True), guild.me: discord.PermissionOverwrite(send_messages=True, manage_channels=True, read_messages=True) }
            try:
                category = discord.utils.get(guild.categories, name="Twitch") or await guild.create_category("Twitch")
                channel = await guild.create_text_channel(name="⚫｜offline", overwrites=overwrites, category=category, reason="Twitch Alert Setup")
            except discord.Forbidden:
                 return False, "Fehler: Bot hat keine Rechte, eine Kategorie oder einen Kanal zu erstellen."
        
        status_config.update({
            "twitch_user": stream_info['login'], "display_name": stream_info['display_name'], "profile_image_url": stream_info['profile_image_url'],
            "channel_id": channel.id, "role_id": role_id, 
            "is_live": None, "message_id": None
        })
        self.bot.data.save_guild_data(guild_id, "twitch_alerts", status_config)
        
        if self.check_stream_status.is_running():
            self.check_stream_status.restart()
        else:
            self.check_stream_status.start()
            
        return True, f"Twitch-Alert für '{stream_info['display_name']}' wurde in {channel.mention} konfiguriert."

async def setup(bot: commands.Bot):
    """Setup-Funktion, um den Cog zum Bot hinzuzufügen."""
    await bot.add_cog(TwitchLiveAlertCog(bot))