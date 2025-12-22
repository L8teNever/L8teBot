# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
from discord import Forbidden, HTTPException
import datetime

class StreakCog(commands.Cog, name="Streak"):
    """Cog für das Aktivitäts-Streak-System."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_streaks.start()

    def cog_unload(self):
        """Wird aufgerufen, wenn der Cog entladen wird."""
        self.check_streaks.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Prüfen, ob das Modul für den Server aktiviert ist
        guild_config = self.bot.data.get_server_config(message.guild.id)
        is_enabled = 'Streak' in guild_config.get('enabled_cogs', [])
        if not is_enabled:
            return

        user_id_str = str(message.author.id)
        today = datetime.date.today()

        # Daten für den Server und User holen/initialisieren
        guild_streaks = self.bot.data.get_guild_data(message.guild.id, "streaks")
        user_data = guild_streaks.setdefault(user_id_str, {
            "current_streak": 0,
            "last_message_date": None
        })

        last_date = None
        if user_data["last_message_date"]:
            try:
                last_date = datetime.date.fromisoformat(user_data["last_message_date"])
            except (ValueError, TypeError):
                last_date = None # Behandelt ungültiges Datumsformat

        # Streak-Logik
        if last_date == today:
            return # Bereits heute aktiv, keine Änderung

        previous_streak = user_data["current_streak"]
        
        if last_date and (today - last_date).days == 1:
            # Streak wird fortgesetzt
            user_data["current_streak"] += 1
        else:
            # Streak ist gebrochen oder neu
            user_data["current_streak"] = 1
        
        user_data["last_message_date"] = today.isoformat()

        # Rollen nur aktualisieren, wenn sich der Streak geändert hat
        if user_data["current_streak"] != previous_streak:
             await self._update_streak_role(message.guild, message.author, user_data["current_streak"])

        self.bot.data.save_guild_data(message.guild.id, "streaks", guild_streaks)

    async def _update_streak_role(self, guild: discord.Guild, member: discord.Member, new_streak: int):
        """Verwaltet die Streak-Rollen für einen Benutzer."""
        # Alte Streak-Rollen entfernen
        roles_to_remove = [role for role in member.roles if role.name.startswith("🔥")]
        if roles_to_remove:
            try:
                await member.remove_roles(*roles_to_remove, reason="Streak-Rolle aktualisiert")
            except (Forbidden, HTTPException):
                print(f"Keine Berechtigung, Rollen für {member} in {guild} zu entfernen.")
        
        # Keine Rolle für 1-Tages-Streak
        if new_streak < 2:
            return

        # Neue Rolle hinzufügen
        new_role_name = f"🔥 {new_streak} Tage Streak"
        streak_role = discord.utils.get(guild.roles, name=new_role_name)

        if not streak_role:
            try:
                streak_role = await guild.create_role(name=new_role_name, reason=f"Streak-Belohnung für {new_streak} Tage")
            except (Forbidden, HTTPException):
                print(f"Keine Berechtigung, Rollen in {guild} zu erstellen.")
                return
        
        if streak_role:
            try:
                await member.add_roles(streak_role, reason=f"Erreichte einen {new_streak}-Tage-Streak")
            except (Forbidden, HTTPException):
                print(f"Keine Berechtigung, Rollen an {member} in {guild} zu vergeben.")

    @tasks.loop(time=datetime.time(hour=0, minute=5, tzinfo=datetime.timezone.utc))
    async def check_streaks(self):
        """Überprüft täglich alle Streaks und setzt sie bei Inaktivität zurück."""
        await self.bot.wait_until_ready()
        today = datetime.date.today()
        
        for guild in self.bot.guilds:
            guild_config = self.bot.data.get_server_config(guild.id)
            if 'Streak' not in guild_config.get('enabled_cogs', []):
                continue

            guild_streaks = self.bot.data.get_guild_data(guild.id, "streaks")
            users_to_remove_streak = []

            for user_id_str, data in guild_streaks.items():
                last_date = datetime.date.fromisoformat(data["last_message_date"]) if data.get("last_message_date") else None
                if last_date and (today - last_date).days > 1:
                    users_to_remove_streak.append(user_id_str)
                    member = guild.get_member(int(user_id_str))
                    if member:
                        roles_to_remove = [role for role in member.roles if role.name.startswith("🔥")]
                        if roles_to_remove:
                            try:
                                await member.remove_roles(*roles_to_remove, reason="Streak gebrochen")
                            except (Forbidden, HTTPException): pass

            if users_to_remove_streak:
                for user_id_str in users_to_remove_streak:
                    if user_id_str in guild_streaks:
                        del guild_streaks[user_id_str]
                self.bot.data.save_guild_data(guild.id, "streaks", guild_streaks)

    async def web_get_streaks(self, guild_id: int) -> list:
        """Holt eine Liste aller aktiven Streaks für das Web-Dashboard."""
        guild = self.bot.get_guild(guild_id)
        if not guild: return []
        guild_streaks = self.bot.data.get_guild_data(guild_id, "streaks")
        streak_list = []
        for user_id_str, data in guild_streaks.items():
            if not user_id_str.isdigit():
                continue
            member = guild.get_member(int(user_id_str))
            if member:
                streak_list.append({"member": member, "streak": data.get("current_streak", 0), "last_active": data.get("last_message_date", "N/A")})
        return sorted(streak_list, key=lambda x: x['streak'], reverse=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(StreakCog(bot))
