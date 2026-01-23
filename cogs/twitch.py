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
            print("FEHLER: Twitch Client ID/Secret nicht in config.json gefunden. Der Twitch-Cog wird nicht gestartet.")
            return
        await self.get_twitch_oauth_token()
        # Nach dem Neustart: Prüfe, ob gespeicherte Nachrichten noch existieren, sonst setze live_message_id auf None
        await self._validate_live_messages_after_restart()
        if self.TWITCH_OAUTH_TOKEN:
            self.check_streams.start()
        else:
            print("FEHLER: Konnte keinen Twitch OAuth Token erhalten. Der Twitch-Cog wird nicht gestartet.")

    async def _validate_live_messages_after_restart(self):
        """Nach einem Neustart prüft diese Funktion, ob gespeicherte Nachrichten noch existieren, und entfernt ungültige IDs."""
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
    async def web_set_feed_config(self, guild_id: int, feed_channel_id: Optional[int], display_mode: str = "channel") -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."
        
        guild_data = self.bot.data.get_guild_data(guild_id, "streamers")
        guild_data["channel_id"] = feed_channel_id
        guild_data["display_mode"] = display_mode
        
        self.bot.data.save_guild_data(guild_id, "streamers", guild_data)
        
        if feed_channel_id:
            channel = guild.get_channel(feed_channel_id)
            if not channel:
                return False, "Kanal nicht gefunden."
            
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

async def setup(bot: commands.Bot):
    await bot.add_cog(TwitchCog(bot))
