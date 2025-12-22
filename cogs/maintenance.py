import discord
from discord.ext import commands, tasks
import asyncio
import random
import os
import sys
import subprocess
from utils.config import BASE_DIR

class Maintenance(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.all_bot_activities = [
            {"name": "mit dem !help Befehl", "type": discord.ActivityType.playing},
            {"name": "Kocht Nudeln", "type": discord.ActivityType.playing},
            {"name": "Tetris mit Daten", "type": discord.ActivityType.playing},
            {"name": "404: Spiel nicht gefunden", "type": discord.ActivityType.playing},
            {"name": "Schere, Stein, API", "type": discord.ActivityType.playing},
            {"name": "mit euren Nerven", "type": discord.ActivityType.playing},
            {"name": "euch gegeneinander aus", "type": discord.ActivityType.playing},
            {"name": "den Babysitter", "type": discord.ActivityType.playing},
            {"name": "mit dem Feuer", "type": discord.ActivityType.playing},
            {"name": "euch zu.", "type": discord.ActivityType.watching},
            {"name": "dem Chaos zu", "type": discord.ActivityType.watching},
            {"name": "{member_count} Usern zu", "type": discord.ActivityType.watching},
            {"name": "Katzenvideos", "type": discord.ActivityType.watching},
            {"name": "in eure Köpfe", "type": discord.ActivityType.watching},
            {"name": "euch beim Failen zu", "type": discord.ActivityType.watching},
            {"name": "wie ihr versucht, mich zu überlisten", "type": discord.ActivityType.watching},
            {"name": "den Server-Logs", "type": discord.ActivityType.watching},
            {"name": "auf !help", "type": discord.ActivityType.listening},
            {"name": "euren Wünschen zu", "type": discord.ActivityType.listening},
            {"name": "das Summen der Daten", "type": discord.ActivityType.listening},
            {"name": "auf neue Befehle", "type": discord.ActivityType.listening},
            {"name": "den Community-Vibes", "type": discord.ActivityType.listening},
            {"name": "euren Ausreden zu", "type": discord.ActivityType.listening},
            {"name": "dem Ping der API", "type": discord.ActivityType.listening},
            {"name": "gegen Bugs an", "type": discord.ActivityType.competing},
            {"name": "der Emoji-Olympiade", "type": discord.ActivityType.competing},
            {"name": "der Ignorier-WM", "type": discord.ActivityType.competing},
            {"name": "eure Fails", "type": discord.ActivityType.streaming, "url": "https://www.twitch.tv/l8tenever"},
            {"name": "auf {guild_count} Servern", "type": discord.ActivityType.watching},
        ]
        self.current_activity_index = 0

    async def cog_load(self):
        self.activity_loop.start()
        self.backup_loop.start()

    async def cog_unload(self):
        self.activity_loop.cancel()
        self.backup_loop.cancel()

    @tasks.loop(minutes=30)
    async def activity_loop(self):
        try:
            random.shuffle(self.all_bot_activities)
            activity_data = self.all_bot_activities[self.current_activity_index]
            activity_name = activity_data["name"]

            if "{member_count}" in activity_name:
                total_members = sum(guild.member_count for guild in self.bot.guilds)
                activity_name = activity_name.replace("{member_count}", str(total_members))

            if "{guild_count}" in activity_name:
                guild_count = len(self.bot.guilds)
                activity_name = activity_name.replace("{guild_count}", str(guild_count))

            activity_type = activity_data["type"]
            activity = discord.Activity(type=activity_type, name=activity_name)

            if activity_type == discord.ActivityType.streaming:
                stream_url = activity_data.get("url", "https://www.twitch.tv/l8tenever")
                activity = discord.Streaming(name=activity_name, url=stream_url)

            await self.bot.change_presence(activity=activity)
            self.current_activity_index = (self.current_activity_index + 1) % len(self.all_bot_activities)
        except Exception as e:
            print(f"Fehler beim Aktualisieren der Bot-Aktivität: {e}")

    @activity_loop.before_loop
    async def before_activity_loop(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=6)
    async def backup_loop(self):
        try:
            print("\n🔄 Starte automatisches Backup...")
            backup_script = os.path.join(BASE_DIR, 'auto_backup.py')
            
            if os.path.exists(backup_script):
                # Führe das Backup-Skript aus
                result = subprocess.run(
                    [sys.executable, backup_script],
                    cwd=BASE_DIR,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    print("✅ Automatisches Backup erfolgreich")
                else:
                    print(f"⚠️  Backup mit Fehlern: {result.stderr}")
            else:
                print("⚠️  Backup-Skript nicht gefunden")
            
        except Exception as e:
            print(f"❌ Fehler beim automatischen Backup: {e}")

    @backup_loop.before_loop
    async def before_backup_loop(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(300) # Warte 5 Minuten nach Start

async def setup(bot):
    await bot.add_cog(Maintenance(bot))
