# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
from twitchAPI.twitch import Twitch
from twitchAPI.helper import first
import asyncio
from typing import Optional, Dict, Any, Tuple, Set

class TwitchClipsCog(commands.Cog, name="Twitch-Clips"):
    """
    Cog zur Überwachung von Twitch-Streamern und zum automatischen Posten
    neu erstellter Clips in einem festgelegten Kanal.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.posted_clips: Dict[int, Set[str]] = {}  # guild_id -> {clip_id, ...}
        self.twitch_api: Optional[Twitch] = None
        self.bot.loop.create_task(self.initialize_cog())

    async def initialize_cog(self):
        """Initialisiert den Cog und startet den Überwachungs-Loop."""
        await self.bot.wait_until_ready()
        client_id = self.bot.config.get("TWITCH_CLIENT_ID")
        client_secret = self.bot.config.get("TWITCH_CLIENT_SECRET")

        if not client_id or not client_secret:
            print("FEHLER: Twitch Client ID/Secret nicht in config.json gefunden. Der Twitch-Clips-Cog wird nicht gestartet.")
            return
        
        try:
            self.twitch_api = await Twitch(client_id, client_secret)
            print("-> Twitch-Clips-Cog erfolgreich mit der Twitch API verbunden.")
            await self.populate_initial_clips()
            self.check_for_new_clips_task.start()
        except Exception as e:
            print(f"FEHLER beim Initialisieren des Twitch-Clips-Cogs: {e}")

    def cog_unload(self):
        """Wird aufgerufen, wenn der Cog entladen wird."""
        self.check_for_new_clips_task.cancel()

    async def populate_initial_clips(self):
        """Füllt den Cache mit den neuesten Clips, um Spam beim Start zu verhindern."""
        if not self.twitch_api: return
        print("Fülle initialen Clip-Cache, um Spam zu vermeiden...")
        
        for guild in self.bot.guilds:
            if not self.is_module_enabled(guild.id): continue
            
            config = self.bot.data.get_guild_data(guild.id, "twitch_clips")
            streamer_name = config.get("streamer_name")
            if not streamer_name: continue

            try:
                user = await first(self.twitch_api.get_users(logins=[streamer_name]))
                if user:
                    self.posted_clips[guild.id] = set()
                    async for clip in self.twitch_api.get_clips(broadcaster_id=user.id, first=20):
                        self.posted_clips[guild.id].add(clip.id)
            except Exception as e:
                print(f"Fehler beim Füllen des Clip-Caches für Server {guild.id}: {e}")
        print("Initialer Clip-Cache gefüllt.")

    def is_module_enabled(self, guild_id: int) -> bool:
        """Prüft, ob das Modul für einen bestimmten Server aktiviert ist."""
        guild_config = self.bot.data.get_server_config(guild_id)
        return self.qualified_name in guild_config.get('enabled_cogs', [])

    @tasks.loop(seconds=30)
    async def check_for_new_clips_task(self):
        """Überprüft periodisch alle konfigurierten Streamer auf neue Clips."""
        if not self.twitch_api: return
        
        for guild in self.bot.guilds:
            config = self.bot.data.get_guild_data(guild.id, "twitch_clips")
            
            if not self.is_module_enabled(guild.id) or not config.get("streamer_name") or not config.get("channel_id"):
                continue

            await self.process_single_guild(guild.id, config)
            await asyncio.sleep(2) # Kleiner Delay zwischen den Servern

    @check_for_new_clips_task.before_loop
    async def before_check_clips_task(self):
        await self.bot.wait_until_ready()

    async def process_single_guild(self, guild_id: int, config: Dict[str, Any]):
        """Verarbeitet die Clip-Suche für einen einzelnen Server."""
        streamer_name = config["streamer_name"]
        channel_id = config["channel_id"]

        guild = self.bot.get_guild(guild_id)
        channel = guild.get_channel(channel_id) if guild else None

        if not guild or not channel:
            return

        try:
            user = await first(self.twitch_api.get_users(logins=[streamer_name]))
            if not user: return
            
            # Initialisiere das Set für die Gilde, falls es noch nicht existiert
            if guild_id not in self.posted_clips:
                self.posted_clips[guild_id] = set()

            async for clip in self.twitch_api.get_clips(broadcaster_id=user.id, first=10):
                if clip.id not in self.posted_clips.get(guild_id, set()):
                    self.posted_clips[guild_id].add(clip.id)
                    
                    embed = discord.Embed(
                        title=clip.title,
                        url=clip.url,
                        color=discord.Color.purple(),
                    )
                    embed.set_image(url=clip.thumbnail_url)
                    
                    game_name = "N/A"
                    if clip.game_id:
                        game = await first(self.twitch_api.get_games(game_ids=[clip.game_id]))
                        if game: game_name = game.name
                        
                    embed.add_field(name="🎮 Kategorie", value=game_name, inline=True)
                    embed.add_field(name="👑 Creator", value=clip.creator_name, inline=True)
                    timestamp = int(clip.created_at.timestamp())
                    embed.add_field(name="🗓️ Erstellt", value=f"<t:{timestamp}:R>", inline=True)
                    
                    profile_image = getattr(user, 'profile_image_url', None)
                    embed.set_footer(text=f"Clip von {clip.broadcaster_name}", icon_url=profile_image)

                    view = discord.ui.View().add_item(discord.ui.Button(label="Watch Clip", style=discord.ButtonStyle.link, url=clip.url, emoji="📺"))
                    
                    await channel.send(embed=embed, view=view)

        except Exception as e:
            print(f"Fehler beim Abrufen von Clips für {streamer_name} auf Server {guild_id}: {e}")

    # --- Web API Methoden ---
    async def web_set_config(self, guild_id: int, streamer_name: str, channel_id: Optional[int]) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."

        config = self.bot.data.get_guild_data(guild_id, "twitch_clips")
        
        # Leere Eingabe löscht die Konfiguration
        if not streamer_name or not channel_id:
            config["streamer_name"] = None
            config["channel_id"] = None
            self.bot.data.save_guild_data(guild_id, "twitch_clips", config)
            return True, "Clip-Benachrichtigungen deaktiviert."

        # Überprüfen, ob der Streamer existiert
        if self.twitch_api:
            user = await first(self.twitch_api.get_users(logins=[streamer_name]))
            if not user:
                return False, f"Twitch-Benutzer '{streamer_name}' konnte nicht gefunden werden."
            streamer_name = user.login # Korrekten Namen verwenden
        
        config["streamer_name"] = streamer_name
        config["channel_id"] = channel_id
        
        self.bot.data.save_guild_data(guild_id, "twitch_clips", config)
        
        # Cache für diesen Server neu aufbauen
        self.posted_clips[guild_id] = set()
        if self.twitch_api and user:
            async for clip in self.twitch_api.get_clips(broadcaster_id=user.id, first=20):
                self.posted_clips[guild_id].add(clip.id)
                
        return True, "Einstellungen für Twitch-Clips erfolgreich gespeichert."

async def setup(bot: commands.Bot):
    await bot.add_cog(TwitchClipsCog(bot))