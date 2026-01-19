# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
import datetime

class MonthlyStatsCog(commands.Cog, name="MonthlyStats"):
    """Cog für monatliche Statistiken - unabhängig vom Level-System."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cleanup_old_months.start()
        self.monthly_reset.start()
    
    def cog_unload(self):
        """Wird aufgerufen, wenn der Cog entladen wird."""
        self.cleanup_old_months.cancel()
        self.monthly_reset.cancel()
    
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
    
    @tasks.loop(time=datetime.time(hour=0, minute=1, tzinfo=datetime.timezone.utc))
    async def monthly_reset(self):
        """Initialisiert den neuen Monat am 1. jeden Monats."""
        await self.bot.wait_until_ready()
        
        now = datetime.datetime.now()
        
        # Nur am 1. des Monats ausführen
        if now.day != 1:
            return
        
        current_month = now.strftime('%Y-%m')
        previous_month = (now.replace(day=1) - datetime.timedelta(days=1)).strftime('%Y-%m')
        
        print(f"🗓️ Monatswechsel: {previous_month} → {current_month}")
        
        for guild in self.bot.guilds:
            monthly_stats = self.bot.data.get_guild_data(guild.id, "monthly_stats")
            
            # Initialisiere neuen Monat (falls noch nicht vorhanden)
            if current_month not in monthly_stats:
                monthly_stats[current_month] = {}
                self.bot.data.save_guild_data(guild.id, "monthly_stats", monthly_stats)
                print(f"✅ Neuer Monat {current_month} initialisiert für {guild.name}")
            
            # Optional: Sende Benachrichtigung in Leaderboard-Channel
            leaderboard_config = self.bot.data.get_guild_data(guild.id, "leaderboard_config")
            channel_id = leaderboard_config.get('leaderboard_channel_id')
            summary_channel_id = leaderboard_config.get('monthly_summary_channel_id')
            
            if channel_id:
                channel = guild.get_channel(channel_id)
                if channel:
                    try:
                        # Erstelle Embed mit Monatsstatistiken
                        prev_month_data = monthly_stats.get(previous_month, {})
                        total_messages = sum(user.get('total_messages', 0) for user in prev_month_data.values())
                        total_users = len(prev_month_data)
                        
                        embed = discord.Embed(
                            title="📊 Neuer Monat!",
                            description=f"Der Monat **{current_month}** hat begonnen!\n\nDie Nachrichtenzähler wurden zurückgesetzt.",
                            color=discord.Color.green(),
                            timestamp=now
                        )
                        
                        if total_messages > 0:
                            embed.add_field(
                                name=f"📈 Statistik {previous_month}",
                                value=f"**{total_messages:,}** Nachrichten von **{total_users}** Nutzern",
                                inline=False
                            )
                        
                        embed.set_footer(text=f"{guild.name} • Monatliches Leaderboard")
                        
                        await channel.send(embed=embed)
                    except Exception as e:
                        print(f"Fehler beim Senden der Monats-Benachrichtigung für {guild.name}: {e}")
            
            # Sende detaillierte Zusammenfassung in separaten Channel (falls konfiguriert)
            if summary_channel_id:
                summary_channel = guild.get_channel(summary_channel_id)
                if summary_channel:
                    try:
                        prev_month_data = monthly_stats.get(previous_month, {})
                        
                        if prev_month_data:
                            # Erstelle Leaderboard für den Vormonat
                            leaderboard = []
                            for user_id_str, user_data in prev_month_data.items():
                                if not user_id_str.isdigit():
                                    continue
                                member = guild.get_member(int(user_id_str))
                                if member:
                                    leaderboard.append({
                                        'member': member,
                                        'messages': user_data.get('total_messages', 0)
                                    })
                            
                            # Sortiere nach Nachrichten
                            leaderboard.sort(key=lambda x: x['messages'], reverse=True)
                            top_10 = leaderboard[:10]
                            
                            # Erstelle detailliertes Embed
                            embed = discord.Embed(
                                title=f"📊 Monatsrückblick {previous_month}",
                                description=f"Die aktivsten Mitglieder im letzten Monat",
                                color=discord.Color.gold(),
                                timestamp=now
                            )
                            
                            # Top 10 Leaderboard
                            if top_10:
                                leaderboard_text = ""
                                for idx, entry in enumerate(top_10, 1):
                                    medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"`{idx}.`"
                                    leaderboard_text += f"{medal} **{entry['member'].display_name}** - {entry['messages']:,} Nachrichten\n"
                                
                                embed.add_field(
                                    name="🏆 Top 10 Schreiber",
                                    value=leaderboard_text,
                                    inline=False
                                )
                            
                            # Gesamtstatistiken
                            total_messages = sum(e['messages'] for e in leaderboard)
                            total_users = len(leaderboard)
                            avg_messages = total_messages / total_users if total_users > 0 else 0
                            
                            stats_text = f"**Gesamt:** {total_messages:,} Nachrichten\n"
                            stats_text += f"**Aktive Nutzer:** {total_users}\n"
                            stats_text += f"**Durchschnitt:** {avg_messages:.1f} Nachrichten/Nutzer"
                            
                            embed.add_field(
                                name="📈 Statistiken",
                                value=stats_text,
                                inline=False
                            )
                            
                            embed.set_footer(text=f"{guild.name} • Monatliche Zusammenfassung")
                            
                            await summary_channel.send(embed=embed)
                    except Exception as e:
                        print(f"Fehler beim Senden der Monats-Zusammenfassung für {guild.name}: {e}")

    
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
