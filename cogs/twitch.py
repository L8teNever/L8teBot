# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import asyncio
import aiohttp
from typing import Optional, Dict, Any, Tuple

class TwitchCog(commands.Cog, name="Twitch"):
    """Cog für die Twitch-Integration."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.TWITCH_CLIENT_ID = self.bot.config.get("TWITCH_CLIENT_ID")
        self.TWITCH_CLIENT_SECRET = self.bot.config.get("TWITCH_CLIENT_SECRET")
        self.TWITCH_OAUTH_TOKEN: Optional[str] = None
        self.bot.loop.create_task(self.initialize_cog())

    async def initialize_cog(self):
        """Initialisiert den Cog, holt den Token und startet den Loop."""
        await self.bot.wait_until_ready()
        if not self.TWITCH_CLIENT_ID or not self.TWITCH_CLIENT_SECRET:
            print("FEHLER: Twitch Client ID/Secret nicht in der Konfiguration (Env oder config.json) gefunden. Der Twitch-Cog wird nicht gestartet.")
            return
        await self.get_twitch_oauth_token()
        # Nach dem Neustart: Prüfe, ob gespeicherte Nachrichten noch existieren, sonst setze live_message_id auf None
        await self._validate_live_messages_after_restart()
        
        # Persistente Views registrieren (für Buttons/Menus nach Neustart)
        self.bot.add_view(TwitchSettingsView(self.bot))
        
        if self.TWITCH_OAUTH_TOKEN:
            self.check_streams.start()
        else:
            print("FEHLER: Konnte keinen Twitch OAuth Token erhalten. Der Twitch-Cog wird nicht gestartet.")

    async def _validate_live_messages_after_restart(self):
        # ... (bestehender Code bleibt unverändert) ...
        for guild in self.bot.guilds:
            guild_data = self.bot.data.get_guild_data(guild.id, "streamers")
            if "streamers" in guild_data:
                feed_channel_id = guild_data.get("channel_id")
                channel = guild.get_channel(feed_channel_id) if feed_channel_id else None
                display_mode = guild_data.get("display_mode", "channel")
                
                # Forum-Mode: Threads validieren
                if display_mode == "forum" and isinstance(channel, discord.ForumChannel):
                    for streamer_key, streamer_data in list(guild_data["streamers"].items()):
                        thread_id = streamer_data.get("thread_id")
                        if thread_id:
                            thread = channel.get_thread(thread_id)
                            if not thread:
                                # Thread existiert nicht mehr
                                streamer_data["thread_id"] = None
                                streamer_data["is_live"] = False
                
                # Kanal-Mode: Nachrichten validieren
                elif display_mode == "channel" and isinstance(channel, discord.TextChannel):
                    for streamer_key, streamer_data in list(guild_data["streamers"].items()):
                        msg_id = streamer_data.get("live_message_id")
                        if msg_id and channel:
                            try:
                                await channel.fetch_message(msg_id)
                            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                                streamer_data["live_message_id"] = None
                                streamer_data["is_live"] = False
                
                self.bot.data.save_guild_data(guild.id, "streamers", guild_data)

    def cog_unload(self):
        self.check_streams.cancel()

    async def get_twitch_oauth_token(self):
        """Holt einen neuen OAuth-Token von Twitch."""
        url = f"https://id.twitch.tv/oauth2/token?client_id={self.TWITCH_CLIENT_ID}&client_secret={self.TWITCH_CLIENT_SECRET}&grant_type=client_credentials"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        self.TWITCH_OAUTH_TOKEN = data['access_token']
                        print("Neuer Twitch OAuth Token erhalten.")
                    else:
                        print(f"Fehler beim Holen des Twitch Tokens: {response.status} - {await response.text()}")
                        self.TWITCH_OAUTH_TOKEN = None
        except Exception as e:
            print(f"Netzwerkfehler beim Holen des Twitch Tokens: {e}")
            self.TWITCH_OAUTH_TOKEN = None

    async def get_twitch_user_data(self, streamer_name: str) -> Optional[Dict]:
        """Holt Benutzerdaten von Twitch anhand des Namens."""
        if not self.TWITCH_OAUTH_TOKEN: return None
        headers = {"Client-ID": self.TWITCH_CLIENT_ID, "Authorization": f"Bearer {self.TWITCH_OAUTH_TOKEN}"}
        url = f"https://api.twitch.tv/helix/users?login={streamer_name}"
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data['data'][0] if data.get('data') else None
                return None

    async def get_stream_data(self, twitch_user_id: str) -> Optional[Dict]:
        """Prüft, ob ein Streamer live ist."""
        if not self.TWITCH_OAUTH_TOKEN: return None
        headers = {"Client-ID": self.TWITCH_CLIENT_ID, "Authorization": f"Bearer {self.TWITCH_OAUTH_TOKEN}"}
        url = f"https://api.twitch.tv/helix/streams?user_id={twitch_user_id}"
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url) as response:
                if response.status == 401: # Token abgelaufen
                    await self.get_twitch_oauth_token()
                    return await self.get_stream_data(twitch_user_id) # Erneuter Versuch mit neuem Token
                if response.status == 200:
                    data = await response.json()
                    return data['data'][0] if data.get('data') else None
                return None

    @tasks.loop(minutes=2)
    async def check_streams(self):
        """Überprüft periodisch alle gespeicherten Streamer."""
        for guild in self.bot.guilds:
            guild_data = self.bot.data.get_guild_data(guild.id, "streamers")
            if "streamers" in guild_data:
                for streamer_key, streamer_data in list(guild_data["streamers"].items()):
                    await self.process_streamer_status(guild.id, streamer_key, streamer_data)
                    await asyncio.sleep(1) # Kleiner Delay zwischen den API-Aufrufen

    async def process_streamer_status(self, guild_id: int, streamer_key: str, data: dict):
        guild = self.bot.get_guild(guild_id)
        if not guild: return

        twitch_id, is_live_cached = data.get("twitch_id"), data.get("is_live", False)
        stream_data = await self.get_stream_data(twitch_id)
        is_live_now = stream_data is not None

        # Wenn der Status unverändert offline ist, nichts tun.
        if not is_live_now and not is_live_cached:
            return

        guild_data = self.bot.data.get_guild_data(guild_id, "streamers")
        feed_channel_id = guild_data.get("channel_id")
        display_mode = guild_data.get("display_mode", "channel")  # "channel" oder "forum"
        channel = guild.get_channel(feed_channel_id)
        if not channel: return

        save_needed = False
        
        try:
            # FORUM-MODUS: Jeder Streamer bekommt einen eigenen Thread
            if display_mode == "forum" and isinstance(channel, discord.ForumChannel):
                await self._process_forum_mode(guild, channel, streamer_key, data, stream_data, is_live_now, is_live_cached, guild_data)
            
            # KANAL-MODUS: Alle Streamer in einem normalen Textkanal
            else:
                await self._process_channel_mode(guild, channel, streamer_key, data, stream_data, is_live_now, is_live_cached, guild_data)

        except (discord.Forbidden, discord.HTTPException) as e:
            print(f"Fehler beim Senden/Bearbeiten der Twitch-Benachrichtigung: {e}")

    async def _process_forum_mode(self, guild, forum_channel, streamer_key, data, stream_data, is_live_now, is_live_cached, guild_data):
        """Verarbeitet Streamer-Status im Forum-Modus (eigener Thread pro Streamer)."""
        save_needed = False
        
        # Fall 1: Stream geht live -> Thread erstellen
        if is_live_now and not is_live_cached:
            role = guild.get_role(data.get("notification_role_id"))
            mention = f"Hey {role.mention}, {data['display_name']} ist LIVE!" if role else f"{data['display_name']} ist LIVE!"
            twitch_url = f"https://twitch.tv/{stream_data['user_login']}"

            embed = discord.Embed(title=stream_data.get('title', 'Kein Titel'), url=twitch_url, color=discord.Color.purple())
            embed.set_author(name=f"{data['display_name']}", url=twitch_url, icon_url=data.get('profile_image_url'))
            embed.add_field(name="Spiel", value=stream_data.get('game_name', 'N/A'), inline=True)
            embed.add_field(name="Zuschauer", value=stream_data.get('viewer_count', 'N/A'), inline=True)
            thumb_url = stream_data.get('thumbnail_url', '').replace('{width}', '1280').replace('{height}', '720')
            if thumb_url: embed.set_image(url=f"{thumb_url}?t={int(asyncio.get_event_loop().time())}")

            view = discord.ui.View().add_item(discord.ui.Button(label="Zum Stream!", style=discord.ButtonStyle.link, url=twitch_url))
            
            try:
                # Thread erstellen
                thread, message = await forum_channel.create_thread(
                    name=f"🔴 {data['display_name']} ist LIVE!",
                    content=mention,
                    embed=embed,
                    view=view,
                    auto_archive_duration=60,  # 1 Stunde
                    reason=f"Twitch Stream Alert für {data['display_name']}"
                )
                
                # Thread sperren (niemand kann antworten)
                try:
                    await thread.edit(locked=True)
                except:
                    pass
                
                data["forum_thread_id"] = thread.id
                data["live_message_id"] = message.id
                data["is_live"] = True
                save_needed = True
                print(f"✅ Forum-Thread erstellt für {data['display_name']}")
                
            except Exception as e:
                print(f"Fehler beim Erstellen des Forum-Threads: {e}")

        # Fall 2: Stream ist noch live -> Thread-Nachricht aktualisieren
        elif is_live_now and is_live_cached:
            import time
            now = time.time()
            last_update = data.get("last_update", 0)
            
            if now - last_update >= 300:  # 5 Minuten
                thread_id = data.get("forum_thread_id")
                if thread_id:
                    try:
                        thread = forum_channel.get_thread(thread_id)
                        if not thread:
                            thread = await forum_channel.fetch_thread(thread_id)
                        
                        if thread:
                            # Starter-Message aktualisieren
                            message = thread.starter_message
                            if not message:
                                message = await thread.fetch_message(thread.id)
                            
                            twitch_url = f"https://twitch.tv/{stream_data['user_login']}"
                            embed = discord.Embed(title=stream_data.get('title', 'Kein Titel'), url=twitch_url, color=discord.Color.purple())
                            embed.set_author(name=f"{data['display_name']}", url=twitch_url, icon_url=data.get('profile_image_url'))
                            embed.add_field(name="Spiel", value=stream_data.get('game_name', 'N/A'), inline=True)
                            embed.add_field(name="Zuschauer", value=stream_data.get('viewer_count', 'N/A'), inline=True)
                            thumb_url = stream_data.get('thumbnail_url', '').replace('{width}', '1280').replace('{height}', '720')
                            if thumb_url: embed.set_image(url=f"{thumb_url}?t={int(asyncio.get_event_loop().time())}")
                            
                            view = discord.ui.View().add_item(discord.ui.Button(label="Zum Stream!", style=discord.ButtonStyle.link, url=twitch_url))
                            await message.edit(embed=embed, view=view)
                            
                            data["last_update"] = now
                            save_needed = True
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        # Thread wurde gelöscht oder ist nicht mehr erreichbar
                        data["forum_thread_id"] = None
                        data["live_message_id"] = None
                        data["is_live"] = False
                        save_needed = True

        # Fall 3: Stream geht offline -> Thread löschen
        elif not is_live_now and is_live_cached:
            thread_id = data.get("forum_thread_id")
            if thread_id:
                try:
                    thread = forum_channel.get_thread(thread_id)
                    if not thread:
                        thread = await forum_channel.fetch_thread(thread_id)
                    
                    if thread:
                        await thread.delete()
                        print(f"🗑️ Forum-Thread gelöscht für {data['display_name']} (offline)")
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
                finally:
                    data["forum_thread_id"] = None
                    data["live_message_id"] = None
                    data["is_live"] = False
                    save_needed = True

        if save_needed:
            guild_data["streamers"][streamer_key] = data
            self.bot.data.save_guild_data(guild.id, "streamers", guild_data)

    async def _process_channel_mode(self, guild, channel, streamer_key, data, stream_data, is_live_now, is_live_cached, guild_data):
        """Verarbeitet Streamer-Status im normalen Kanal-Modus."""
        save_needed = False
        
        # Fall 1: Stream ist jetzt live (war es vorher nicht)
        if is_live_now and not is_live_cached:
            role = guild.get_role(data.get("notification_role_id"))
            mention = f"Hey {role.mention}, {data['display_name']} ist LIVE!" if role else f"{data['display_name']} ist LIVE!"
            twitch_url = f"https://twitch.tv/{stream_data['user_login']}"

            embed = discord.Embed(title=stream_data.get('title', 'Kein Titel'), url=twitch_url, color=discord.Color.purple())
            embed.set_author(name=f"{data['display_name']}", url=twitch_url, icon_url=data.get('profile_image_url'))
            embed.add_field(name="Spiel", value=stream_data.get('game_name', 'N/A'), inline=True)
            embed.add_field(name="Zuschauer", value=stream_data.get('viewer_count', 'N/A'), inline=True)
            thumb_url = stream_data.get('thumbnail_url', '').replace('{width}', '1280').replace('{height}', '720')
            if thumb_url: embed.set_image(url=f"{thumb_url}?t={int(asyncio.get_event_loop().time())}")

            view = discord.ui.View().add_item(discord.ui.Button(label="Zum Stream!", style=discord.ButtonStyle.link, url=twitch_url))
            msg = await channel.send(content=mention, embed=embed, view=view)
            data["live_message_id"] = msg.id
            data["is_live"] = True
            save_needed = True

        # Fall 2: Stream ist immer noch live -> Nachricht aktualisieren
        elif is_live_now and is_live_cached:
            import time
            now = time.time()
            last_update = data.get("last_update", 0)
            if now - last_update >= 600:  # 600 Sekunden = 10 Minuten
                if msg_id := data.get("live_message_id"):
                    try:
                        msg = await channel.fetch_message(msg_id)
                        twitch_url = f"https://twitch.tv/{stream_data['user_login']}"

                        embed = discord.Embed(title=stream_data.get('title', 'Kein Titel'), url=twitch_url, color=discord.Color.purple())
                        embed.set_author(name=f"{data['display_name']}", url=twitch_url, icon_url=data.get('profile_image_url'))
                        embed.add_field(name="Spiel", value=stream_data.get('game_name', 'N/A'), inline=True)
                        embed.add_field(name="Zuschauer", value=stream_data.get('viewer_count', 'N/A'), inline=True)
                        thumb_url = stream_data.get('thumbnail_url', '').replace('{width}', '1280').replace('{height}', '720')
                        if thumb_url: embed.set_image(url=f"{thumb_url}?t={int(asyncio.get_event_loop().time())}")

                        await msg.edit(embed=embed)
                        data["last_update"] = now
                        save_needed = True
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        data["live_message_id"] = None
                        data["is_live"] = False
                        save_needed = True
                        # Erneuten Durchlauf erzwingen
                        await self.process_streamer_status(guild.id, streamer_key, data)
                        return 

        # Fall 3: Stream ist jetzt offline (war es vorher)
        elif not is_live_now and is_live_cached:
            if msg_id := data.get("live_message_id"):
                try:
                    msg = await channel.fetch_message(msg_id)
                    await msg.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException): pass
                finally:
                    data["live_message_id"] = None
                    data["is_live"] = False
                    save_needed = True

        if save_needed:
            guild_data["streamers"][streamer_key] = data
            self.bot.data.save_guild_data(guild.id, "streamers", guild_data)

    async def web_set_streamer_command_role(self, guild_id: int, role_id: Optional[int]) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."
        
        guild_data = self.bot.data.get_guild_data(guild_id, "streamers")
        guild_data["streamer_command_role_id"] = role_id
        
        self.bot.data.save_guild_data(guild_id, "streamers", guild_data)
        if role_id:
            role = guild.get_role(role_id)
            role_name = role.name if role else str(role_id)
            return True, f"Streamer-Befehl Rolle auf @{role_name} gesetzt."
        return True, "Streamer-Befehl Rolle deaktiviert."

    @app_commands.command(name="streamer", description="Fügt dir die Streamer-Rolle hinzu und verknüpft deinen Twitch-Namen.")
    @app_commands.describe(username="Dein Twitch-Benutzername")
    async def streamer_command(self, interaction: discord.Interaction, username: str):
        """Befehl um die Streamer-Rolle zu erhalten."""
        guild_id = interaction.guild_id
        if not guild_id: return
        
        guild_data = self.bot.data.get_guild_data(guild_id, "streamers")
        role_id = guild_data.get("streamer_command_role_id")
        
        if not role_id:
            await interaction.response.send_message("❌ Die Streamer-Rolle wurde noch nicht konfiguriert. Bitte kontaktiere einen Administrator.", ephemeral=True)
            return
            
        role = interaction.guild.get_role(role_id)
        if not role:
            await interaction.response.send_message("❌ Die konfigurierte Streamer-Rolle wurde nicht gefunden.", ephemeral=True)
            return
            
        try:
            # Überprüfe Twitch-Existenz (optional, aber gut für Validierung)
            user_data = await self.get_twitch_user_data(username)
            if not user_data:
                await interaction.response.send_message(f"❌ Der Twitch-Benutzer `{username}` konnte nicht gefunden werden.", ephemeral=True)
                return
                
            # Rolle geben
            if role in interaction.user.roles:
                await interaction.response.send_message(f"ℹ️ Du hast die Rolle {role.mention} bereits.", ephemeral=True)
                return
                
            await interaction.user.add_roles(role, reason=f"Streamer-Level verifiziert (Twitch: {username})")
            
            # Speichere die Verknüpfung (optional, aber nützlich)
            user_streamers = self.bot.data.get_guild_data(guild_id, "user_twitch_links")
            user_streamers[str(interaction.user.id)] = username
            self.bot.data.save_guild_data(guild_id, "user_twitch_links", user_streamers)
            
            await interaction.response.send_message(f"✅ Erfoglreich! Du hast nun die Rolle {role.mention} erhalten. Viel Spaß beim Streamen!", ephemeral=True)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ Ich habe keine Berechtigung, dir diese Rolle zu geben. (Rollen-Hierarchie prüfen!)", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ein Fehler ist aufgetreten: {e}", ephemeral=True)

    # --- Web API Methoden ---
    async def web_set_feed_config(self, guild_id: int, feed_channel_id: Optional[int], display_mode: str = "channel", auto_assign: bool = False) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."
        
        guild_data = self.bot.data.get_guild_data(guild_id, "streamers")
        
        # Alten Modus speichern BEVOR wir ihn überschreiben
        old_display_mode = guild_data.get("display_mode")
        mode_changed = old_display_mode and old_display_mode != display_mode
        
        guild_data["channel_id"] = feed_channel_id
        guild_data["display_mode"] = display_mode
        guild_data["auto_assign_new_streamers"] = auto_assign
        
        self.bot.data.save_guild_data(guild_id, "streamers", guild_data)
        
        if feed_channel_id:
            channel = guild.get_channel(feed_channel_id)
            if not channel:
                return False, "Kanal nicht gefunden."
            
            # Beim Wechsel des Display-Modus: Alle Streamer-Status zurücksetzen
            if mode_changed:
                streamers = guild_data.get("streamers", {})
                for streamer_key, streamer_data in streamers.items():
                    # Alte Daten zurücksetzen, damit sie im neuen Modus neu erstellt werden
                    streamer_data["is_live"] = False
                    streamer_data["live_message_id"] = None
                    streamer_data["forum_thread_id"] = None
                    streamer_data["last_update"] = 0
                print(f"🔄 Display-Modus gewechselt von '{old_display_mode}' zu '{display_mode}'. Alle Streamer werden neu initialisiert.")
            
            # Automatisch Berechtigungen setzen
            try:
                if display_mode == "forum" and isinstance(channel, discord.ForumChannel):
                    # Forum-Berechtigungen: Niemand kann schreiben oder Threads erstellen
                    await channel.set_permissions(
                        guild.default_role,
                        send_messages=False,
                        send_messages_in_threads=False,
                        create_public_threads=False,
                        create_private_threads=False,
                        view_channel=True,
                        read_message_history=True
                    )
                    
                    # Sofortige Aktualisierung aller Streamer für das neue Forum
                    streamers = guild_data.get("streamers", {})
                    for streamer_key, streamer_data in streamers.items():
                        try:
                            await self.process_streamer_status(guild_id, streamer_key, streamer_data)
                        except Exception as e:
                            print(f"Fehler bei sofortiger Aktualisierung für {streamer_key}: {e}")
                    self.bot.data.save_guild_data(guild_id, "streamers", guild_data)
                    
                    return True, f"Forum '{channel.name}' konfiguriert! Berechtigungen wurden automatisch gesetzt."
                else:
                    # Normaler Kanal: Niemand kann schreiben
                    await channel.set_permissions(
                        guild.default_role,
                        send_messages=False,
                        view_channel=True,
                        read_message_history=True
                    )
                    
                    # Sofortige Aktualisierung aller Streamer für den neuen Kanal
                    streamers = guild_data.get("streamers", {})
                    for streamer_key, streamer_data in streamers.items():
                        try:
                            await self.process_streamer_status(guild_id, streamer_key, streamer_data)
                        except Exception as e:
                            print(f"Fehler bei sofortiger Aktualisierung für {streamer_key}: {e}")
                    self.bot.data.save_guild_data(guild_id, "streamers", guild_data)
                    
                    return True, f"Feed-Kanal auf #{channel.name} gesetzt. Berechtigungen wurden automatisch gesetzt."
            except discord.Forbidden:
                return True, f"Kanal konfiguriert, aber Bot hat keine Berechtigung, die Kanal-Berechtigungen zu ändern."
            except Exception as e:
                return True, f"Kanal konfiguriert, aber Fehler beim Setzen der Berechtigungen: {e}"
        
        return True, "Feed-Kanal deaktiviert."

    async def web_add_streamer(self, guild_id: int, streamer_name: str) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."

        # Parse Twitch URLs to extract username
        streamer_name = streamer_name.strip()
        if "twitch.tv/" in streamer_name:
            streamer_name = streamer_name.split("twitch.tv/")[-1].strip("/").strip()

        user_data = await self.get_twitch_user_data(streamer_name)
        if not user_data:
            return False, f"Twitch-Benutzer '{streamer_name}' konnte nicht gefunden werden."

        twitch_id, correct_name = user_data['id'], user_data['display_name']
        streamer_key = correct_name.lower()
        
        guild_data = self.bot.data.get_guild_data(guild_id, "streamers")
        streamers = guild_data.setdefault("streamers", {})
        
        if streamer_key in streamers:
            return False, f"'{correct_name}' wird bereits verfolgt."
        
        try:
            role = await guild.create_role(name=f"{correct_name}-Ping", reason=f"Ping-Rolle für {correct_name}")
            streamers[streamer_key] = {
                "twitch_id": twitch_id, "display_name": correct_name, 
                "profile_image_url": user_data.get('profile_image_url'),
                "is_live": False, "live_message_id": None, 
                "notification_role_id": role.id
            }
            self.bot.data.save_guild_data(guild_id, "streamers", guild_data)
            
            # Sofortige Aktualisierung für den neuen Streamer
            try:
                await self.process_streamer_status(guild_id, streamer_key, streamers[streamer_key])
                self.bot.data.save_guild_data(guild_id, "streamers", guild_data)
                
                # NEU: Prüfen ob Rollen automatisch an alle verteilt werden sollen
                if guild_data.get("auto_assign_new_streamers"):
                    self.bot.loop.create_task(self._bg_bulk_assign_streamer_roles(guild_id, role.id))
                    return True, f"'{correct_name}' wurde hinzugefügt. Die neue Rolle wird im Hintergrund an alle verteilt."
                
            except Exception as e:
                print(f"Fehler bei sofortiger Aktualisierung für {correct_name}: {e}")
            
            return True, f"'{correct_name}' wurde zum Feed hinzugefügt."
        except (discord.Forbidden, discord.HTTPException) as e:
            return False, f"Fehler beim Erstellen der Rolle: {e}"

    async def web_remove_streamer(self, guild_id: int, streamer_key: str) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."
        
        guild_data = self.bot.data.get_guild_data(guild_id, "streamers")
        streamers = guild_data.get("streamers", {})
        
        data = streamers.pop(streamer_key.lower(), None)
        if not data:
            return False, f"Streamer '{streamer_key}' wurde nicht im Feed gefunden."
        
        if (role_id := data.get("notification_role_id")) and (role := guild.get_role(role_id)):
            try: await role.delete(reason="Streamer aus Feed entfernt.")
            except (discord.Forbidden, discord.HTTPException): pass
            
        self.bot.data.save_guild_data(guild_id, "streamers", guild_data)
        return True, f"'{data.get('display_name', streamer_key)}' wurde aus dem Feed entfernt."

    async def web_set_settings_trigger_role(self, guild_id: int, role_id: Optional[int]) -> Tuple[bool, str]:
        guild_data = self.bot.data.get_guild_data(guild_id, "streamers")
        guild_data["settings_trigger_role_id"] = role_id
        self.bot.data.save_guild_data(guild_id, "streamers", guild_data)
        return True, "Trigger-Rolle für Einstellungen erfolgreich aktualisiert."

    async def web_create_settings_trigger_role(self, guild_id: int) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."
        
        try:
            role = await guild.create_role(
                name="Twitch-Abos verwalten",
                reason="Automatisch erstellte Trigger-Rolle für Twitch-Einstellungen",
                color=discord.Color.purple(),
                mentionable=True
            )
            
            # Direkt als Trigger-Rolle setzen
            await self.web_set_settings_trigger_role(guild_id, role.id)
            return True, f"Rolle `@{role.name}` wurde erstellt und als Trigger gesetzt."
        except Exception as e:
            return False, f"Fehler beim Erstellen der Rolle: {e}"

    async def web_bulk_assign_streamer_roles(self, guild_id: int) -> Tuple[bool, str]:
        # Wir starten das Ganze als Hintergrundtask, damit das Web-Interface nicht blockiert
        self.bot.loop.create_task(self._bg_bulk_assign_streamer_roles(guild_id))
        return True, "Die Rollenverteilung wurde im Hintergrund gestartet. Dies kann bei vielen Mitgliedern einige Minuten dauern."

    async def _bg_bulk_assign_streamer_roles(self, guild_id: int, target_role_id: Optional[int] = None):
        """Hintergrund-Task für die schrittweise Verteilung von Rollen."""
        guild = self.bot.get_guild(guild_id)
        if not guild: return
        
        guild_data = self.bot.data.get_guild_data(guild_id, "streamers")
        streamers_dict = guild_data.get("streamers", {})
        user_prefs = guild_data.get("user_preferences", {})
        
        if not streamers_dict: return

        print(f"DEBUG: Starte Bulk-Rollenverteilung für Server {guild.name} ({guild_id})")
        
        count = 0
        # Wir gehen alle Member durch
        for member in guild.members:
            if member.bot: continue
            
            u_id = str(member.id)
            prefs = user_prefs.get(u_id, {})
            
            roles_to_add = []
            
            if target_role_id:
                # Spezialfall: Nur eine bestimmte Rolle verteilen (z.B. neuer Streamer)
                for s_key, s_data in streamers_dict.items():
                    if s_data.get("notification_role_id") == target_role_id:
                        if prefs.get(s_key) is True: # Opt-In: Nur wenn explizit True
                            role = guild.get_role(target_role_id)
                            if role and role not in member.roles:
                                roles_to_add.append(role)
            else:
                # Normalfall: Alle Streamer-Rollen prüfen
                for s_key, s_data in streamers_dict.items():
                    if prefs.get(s_key) is not True: # Opt-In: Nur wenn explizit True
                        continue
                    
                    role_id = s_data.get("notification_role_id")
                    if not role_id: continue
                    
                    role = guild.get_role(role_id)
                    if role and role not in member.roles:
                        roles_to_add.append(role)
            
            if roles_to_add:
                try:
                    await member.add_roles(*roles_to_add, reason="Twitch-System: Automatische Rollenverteilung")
                    count += 1
                    # Kurze Pause alle paar Rollenänderungen, um API-Limits zu schonen
                    if count % 5 == 0:
                        await asyncio.sleep(1)
                except Exception as e:
                    print(f"DEBUG: Fehler beim Zuweisen von Rollen an {member.name}: {e}")
                    await asyncio.sleep(2) # Längere Pause bei Fehlern
        
        print(f"DEBUG: Bulk-Rollenverteilung abgeschlossen. {count} Mitglieder aktualisiert.")

    async def web_bulk_remove_streamer_roles(self, guild_id: int) -> Tuple[bool, str]:
        """Entfernt alle Twitch-Ping-Rollen von allen Mitgliedern."""
        self.bot.loop.create_task(self._bg_bulk_remove_streamer_roles(guild_id))
        return True, "Die Rollen-Entfernung wurde im Hintergrund gestartet. Dies kann einige Minuten dauern."

    async def _bg_bulk_remove_streamer_roles(self, guild_id: int):
        """Hintergrund-Task für die schrittweise Entfernung von Twitch-Rollen."""
        guild = self.bot.get_guild(guild_id)
        if not guild: return
        
        guild_data = self.bot.data.get_guild_data(guild_id, "streamers")
        streamers_dict = guild_data.get("streamers", {})
        if not streamers_dict: return

        # Alle Rollen-IDs sammeln
        role_ids = []
        for s_data in streamers_dict.values():
            if r_id := s_data.get("notification_role_id"):
                role_ids.append(r_id)
        
        if not role_ids: return

        print(f"DEBUG: Starte Bulk-Rollen-Entfernung für Server {guild.name}")
        
        count = 0
        for member in guild.members:
            if member.bot: continue
            
            roles_to_remove = [r for r in member.roles if r.id in role_ids]
            
            if roles_to_remove:
                try:
                    await member.remove_roles(*roles_to_remove, reason="Twitch-System: Bulk Cleanup")
                    count += 1
                    if count % 5 == 0:
                        await asyncio.sleep(1)
                except Exception as e:
                    print(f"DEBUG: Fehler beim Entfernen von Rollen bei {member.name}: {e}")
                    await asyncio.sleep(2)
        
        print(f"DEBUG: Bulk-Rollen-Entfernung abgeschlossen. {count} Mitglieder bereinigt.")

    async def web_sync_streamer_roles(self, guild_id: int) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."
        
        guild_data = self.bot.data.get_guild_data(guild_id, "streamers")
        streamers_dict = guild_data.get("streamers", {})
        
        if not streamers_dict:
            return False, "Keine Streamer konfiguriert."

        recreated_count = 0
        for s_key, s_data in streamers_dict.items():
            role_id = s_data.get("notification_role_id")
            role = guild.get_role(role_id) if role_id else None
            
            # Falls die Rolle fehlt oder gelöscht wurde
            if not role:
                display_name = s_data.get("display_name", s_key)
                try:
                    role = await guild.create_role(
                        name=f"{display_name}-Ping", 
                        reason=f"Neu erstellte Ping-Rolle für {display_name} (Sync-Button)",
                        color=discord.Color.purple()
                    )
                    s_data["notification_role_id"] = role.id
                    recreated_count += 1
                except (discord.Forbidden, discord.HTTPException) as e:
                    print(f"Fehler beim Erstellen der Rolle für {display_name}: {e}")
        
        if recreated_count > 0:
            self.bot.data.save_guild_data(guild_id, "streamers", guild_data)
            return True, f"{recreated_count} fehlende Rolle(n) wurden erfolgreich neu erstellt."
        
        return True, "Alle Streamer haben bereits ihre Rollen. Keine Aktion erforderlich."

    # --- Listener für Trigger-Rolle ---
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        guild_id = after.guild.id
        guild_data = self.bot.data.get_guild_data(guild_id, "streamers")
        trigger_role_id = guild_data.get("settings_trigger_role_id")
        
        if not trigger_role_id:
            return

        trigger_role = after.guild.get_role(trigger_role_id)
        if not trigger_role:
            return

        # Prüfe ob die Rolle HINZUGEFÜGT wurde
        if trigger_role not in before.roles and trigger_role in after.roles:
            await self._create_user_settings_channel(after, trigger_role)

    async def _create_user_settings_channel(self, member: discord.Member, trigger_role: discord.Role):
        guild = member.guild
        
        # Berechtigungen für den privaten Kanal
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member: discord.PermissionOverwrite(read_messages=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        
        channel_name = f"settings-{member.name}"
        try:
            # Kanal erstellen
            category = discord.utils.get(guild.categories, name="Twitch Setup") or await guild.create_category("Twitch Setup")
            channel = await guild.create_text_channel(name=channel_name, overwrites=overwrites, category=category, reason=f"Einstellungs-Kanal für {member.name}")
            
            # Nachricht mit Dropdown senden
            embed = discord.Embed(
                title="✨ Twitch Benachrichtigungen",
                description=(
                    f"Hallo {member.mention}!\n\n"
                    "Hier kannst du ganz einfach festlegen, bei welchen Streamern du gepingt werden möchtest.\n\n"
                    "**Anleitung:**\n"
                    "1. Wähle im Menü unten alle Streamer aus (Multiselect).\n"
                    "2. Der Bot gibt dir automatisch die entsprechenden Rollen.\n"
                    "3. Klicke auf den grünen Button, wenn du fertig bist."
                ),
                color=discord.Color.purple()
            )
            embed.set_footer(text="Dieses Fenster schließt sich automatisch nach 10 Minuten.")
            
            view = TwitchSettingsView(self.bot, member)
            await channel.send(embed=embed, view=view)
            
            # Timeout Task starten (10 Minuten)
            self.bot.loop.create_task(self._cleanup_settings_channel_after_delay(channel, member, trigger_role))
            
        except Exception as e:
            print(f"DEBUG: Fehler beim Senden der Einstellungs-Nachricht: {e}")
            try:
                await member.send(f"Ich konnte keine Einstellungs-Nachricht in deinem Kanal erstellen: {e}")
                await member.remove_roles(trigger_role, reason="Fehler bei Nachrichtenerstellung")
            except: pass

    async def _cleanup_settings_channel_after_delay(self, channel: discord.TextChannel, member: discord.Member, role: discord.Role):
        await asyncio.sleep(600) # 10 Minuten
        
        # Prüfen ob der Kanal noch existiert
        try:
            exists = self.bot.get_channel(channel.id)
            if exists:
                # Rolle entfernen
                try: await member.remove_roles(role, reason="Timeout für Einstellungen")
                except: pass
                
                # Kanal löschen
                await channel.delete(reason="Timeout für Einstellungs-Kanal")
        except: pass

class StreamerSelect(discord.ui.Select):
    def __init__(self, bot, member=None, streamers_dict=None):
        # Wenn member und streamers_dict da sind, initialisieren wir die Optionen (beim Senden der Nachricht)
        options = []
        if member and streamers_dict:
            current_role_ids = [r.id for r in member.roles]
            for s_key, s_data in list(streamers_dict.items())[:25]:
                role_id = s_data.get("notification_role_id")
                if not role_id: continue
                role = member.guild.get_role(role_id)
                if not role: continue
                has_role = role.id in current_role_ids
                options.append(discord.SelectOption(
                    label=s_data.get("display_name", s_key),
                    value=s_key,
                    description="Status: Abonniert" if has_role else "Status: Nicht abonniert",
                    default=has_role
                ))
        
        if not options:
            options = [discord.SelectOption(label="Keine Streamer konfiguriert", value="none")]
            
        super().__init__(
            custom_id="twitch:settings:select",
            placeholder="Wähle deine Streamer aus...",
            min_values=0,
            max_values=len(options),
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        # Hol dir die aktuellsten Daten für diese Guild
        guild_data = self.view.bot.data.get_guild_data(interaction.guild.id, "streamers")
        streamers_dict = guild_data.get("streamers", {})
        
        member = interaction.user
        selected_keys = self.values
        if "none" in selected_keys:
            selected_keys = []
            
        guild = interaction.guild
        current_role_ids = [r.id for r in member.roles]
        added = []
        removed = []
        
        # Präferenzen speichern (Opt-Out Tracking)
        user_prefs = guild_data.setdefault("user_preferences", {})
        u_id = str(member.id)
        if u_id not in user_prefs:
            user_prefs[u_id] = {}
            
        for s_key, s_data in streamers_dict.items():
            role_id = s_data.get("notification_role_id")
            if not role_id: continue
            role = guild.get_role(role_id)
            if not role: continue
            
            is_now_selected = s_key in selected_keys
            has_role = role.id in current_role_ids
            
            # Status in Datei sichern
            user_prefs[u_id][s_key] = is_now_selected

            if is_now_selected and not has_role:
                await member.add_roles(role, reason="Twitch-Abo: Aktiviert")
                added.append(f"@{role.name}")
            elif not is_now_selected and has_role:
                await member.remove_roles(role, reason="Twitch-Abo: Deaktiviert")
                removed.append(f"@{role.name}")
        
        # Speichern
        self.view.bot.data.save_guild_data(interaction.guild.id, "streamers", guild_data)

        if not added and not removed:
            return await interaction.response.send_message("Keine Änderungen vorgenommen.", ephemeral=True)
            
        msg_parts = []
        if added: msg_parts.append(f"✅ **Aktiviert:** {', '.join(added)}")
        if removed: msg_parts.append(f"❌ **Deaktiviert:** {', '.join(removed)}")
        await interaction.response.send_message("\n".join(msg_parts), ephemeral=True)

class TwitchSettingsView(discord.ui.View):
    def __init__(self, bot, member=None):
        super().__init__(timeout=None)
        self.bot = bot
        
        # Falls wir die View neu erstellen (um sie zu senden), fügen wir das Menü hinzu
        if member:
            guild_data = bot.data.get_guild_data(member.guild.id, "streamers")
            streamers_dict = guild_data.get("streamers", {})
            self.add_item(StreamerSelect(bot, member, streamers_dict))
        else:
            # Für die persistente Registrierung brauchen wir nur das Grundgerüst
            self.add_item(StreamerSelect(bot))

    @discord.ui.button(label="Fertig & Schließen", style=discord.ButtonStyle.green, custom_id="twitch:settings:close")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        guild_id = interaction.guild.id
        
        guild_data = self.bot.data.get_guild_data(guild_id, "streamers")
        trigger_role_id = guild_data.get("settings_trigger_role_id")
        
        await interaction.response.send_message("Einstellungen gespeichert. Der Kanal wird nun gelöscht...")
        
        # Trigger-Rolle entfernen
        if trigger_role_id:
            role = interaction.guild.get_role(trigger_role_id)
            if role:
                try: await member.remove_roles(role, reason="Einstellungen abgeschlossen")
                except: pass
        
        # Kanal löschen
        await asyncio.sleep(2)
        try:
            await interaction.channel.delete(reason="Einstellungs-Kanal geschlossen")
        except: pass

async def setup(bot: commands.Bot):
    await bot.add_cog(TwitchCog(bot))
