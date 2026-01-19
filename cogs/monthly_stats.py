# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
import datetime

class MonthlyStatsCog(commands.Cog, name="MonthlyStats"):
    """Cog für monatliche Statistiken - unabhängig vom Level-System."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cleanup_old_months.start()
    
    def cog_unload(self):
        """Wird aufgerufen, wenn der Cog entladen wird."""
        self.cleanup_old_months.cancel()
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Trackt Nachrichten pro Monat und Channel."""
        if message.author.bot or not message.guild:
            return
        
        # Dieses Modul läuft immer, unabhängig von enabled_cogs
        # Es trackt nur Statistiken, beeinflusst aber nichts
        
        now = datetime.datetime.now()
        current_month = now.strftime('%Y-%m')
        
        user_id_str = str(message.author.id)
        channel_id_str = str(message.channel.id)
        
        # Hole monatliche Statistiken
        monthly_stats = self.bot.data.get_guild_data(message.guild.id, "monthly_stats")
        
        # Initialisiere Monat falls nicht vorhanden
        if current_month not in monthly_stats:
            monthly_stats[current_month] = {}
        
        # Initialisiere User falls nicht vorhanden
        if user_id_str not in monthly_stats[current_month]:
            monthly_stats[current_month][user_id_str] = {
                'total_messages': 0,
                'channels': {},
                'max_streak': 0,
                'last_message_date': None
            }
        
        user_data = monthly_stats[current_month][user_id_str]
        
        # Erhöhe Nachrichtenzähler
        user_data['total_messages'] += 1
        
        # Erhöhe Channel-spezifischen Zähler
        if channel_id_str not in user_data['channels']:
            user_data['channels'][channel_id_str] = 0
        user_data['channels'][channel_id_str] += 1
        
        # Update Streak-Tracking (monatlich)
        today = now.date()
        last_date = None
        
        if user_data['last_message_date']:
            try:
                last_date = datetime.date.fromisoformat(user_data['last_message_date'])
            except (ValueError, TypeError):
                last_date = None
        
        if last_date != today:
            # Neuer Tag
            if last_date and (today - last_date).days == 1:
                # Streak fortsetzen
                current_streak = user_data.get('current_monthly_streak', 0) + 1
            else:
                # Streak neu starten
                current_streak = 1
            
            user_data['current_monthly_streak'] = current_streak
            user_data['last_message_date'] = today.isoformat()
            
            # Update max streak für diesen Monat
            if current_streak > user_data['max_streak']:
                user_data['max_streak'] = current_streak
        
        # Speichern
        self.bot.data.save_guild_data(message.guild.id, "monthly_stats", monthly_stats)
    
    @tasks.loop(hours=24)
    async def cleanup_old_months(self):
        """Entfernt Statistiken, die älter als 12 Monate sind."""
        await self.bot.wait_until_ready()
        
        now = datetime.datetime.now()
        cutoff_date = now - datetime.timedelta(days=365)
        cutoff_month = cutoff_date.strftime('%Y-%m')
        
        for guild in self.bot.guilds:
            monthly_stats = self.bot.data.get_guild_data(guild.id, "monthly_stats")
            
            months_to_remove = []
            for month in monthly_stats.keys():
                if month < cutoff_month:
                    months_to_remove.append(month)
            
            if months_to_remove:
                for month in months_to_remove:
                    del monthly_stats[month]
                
                self.bot.data.save_guild_data(guild.id, "monthly_stats", monthly_stats)
                print(f"Entfernte {len(months_to_remove)} alte Monate für Guild {guild.name}")

async def setup(bot: commands.Bot):
    await bot.add_cog(MonthlyStatsCog(bot))
