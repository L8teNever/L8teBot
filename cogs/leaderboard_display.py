# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
from discord import ButtonStyle, Interaction
from discord.ui import Button, View, Select
import datetime

class LeaderboardView(View):
    """Interaktive View für Leaderboard-Anzeige mit Buttons."""
    
    def __init__(self, bot, guild_id, current_type='messages'):
        super().__init__(timeout=None)  # Persistent view
        self.bot = bot
        self.guild_id = guild_id
        self.current_type = current_type
        
        # Add dropdown for leaderboard type selection
        options = [
            discord.SelectOption(
                label="🗨️ Meiste Nachrichten (Monatlich)",
                value="messages",
                description="Aktivste Nutzer diesen Monat",
                default=(current_type == 'messages')
            ),
            discord.SelectOption(
                label="⭐ Höchstes Level (Allzeit)",
                value="level",
                description="Nutzer mit dem höchsten Level",
                default=(current_type == 'level')
            ),
            discord.SelectOption(
                label="🔥 Längste aktive Streak",
                value="streak_current",
                description="Aktuelle laufende Streaks",
                default=(current_type == 'streak_current')
            ),
            discord.SelectOption(
                label="🏆 Längste Streak (Allzeit)",
                value="streak_alltime",
                description="Hall of Fame - Rekord-Streaks",
                default=(current_type == 'streak_alltime')
            ),
        ]
        
        select = Select(
            placeholder="Leaderboard-Typ wählen...",
            options=options,
            custom_id=f"leaderboard_select_{guild_id}"
        )
        select.callback = self.select_callback
        self.add_item(select)
        
        # Add refresh button
        refresh_btn = Button(
            label="🔄 Aktualisieren",
            style=ButtonStyle.primary,
            custom_id=f"leaderboard_refresh_{guild_id}"
        )
        refresh_btn.callback = self.refresh_callback
        self.add_item(refresh_btn)
    
    async def select_callback(self, interaction: Interaction):
        """Callback wenn ein Leaderboard-Typ ausgewählt wird."""
        selected_type = interaction.data['values'][0]
        
        # Create a temporary view with the selected type to generate the embed
        temp_view = LeaderboardView(self.bot, self.guild_id, selected_type)
        embed = await temp_view.create_leaderboard_embed()
        
        # Send ephemeral response (only visible to the user who clicked)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def refresh_callback(self, interaction: Interaction):
        """Callback für Refresh-Button."""
        # Create embed with current type
        embed = await self.create_leaderboard_embed()
        
        # Send ephemeral response (only visible to the user who clicked)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def create_leaderboard_embed(self):
        """Erstellt das Leaderboard-Embed."""
        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            return discord.Embed(title="Fehler", description="Server nicht gefunden", color=discord.Color.red())
        
        now = datetime.datetime.now()
        current_month = now.strftime('%Y-%m')
        
        leaderboard = []
        title = ""
        description = ""
        
        if self.current_type == 'messages':
            title = "🗨️ Meiste Nachrichten - Monatlich"
            description = f"Aktivste Nutzer im {now.strftime('%B %Y')}"
            monthly_stats = self.bot.data.get_guild_data(self.guild_id, "monthly_stats")
            month_data = monthly_stats.get(current_month, {})
            
            for user_id_str, user_data in month_data.items():
                if not user_id_str.isdigit():
                    continue
                member = guild.get_member(int(user_id_str))
                if not member:
                    continue
                
                msg_count = user_data.get('total_messages', 0)
                if msg_count > 0:
                    leaderboard.append({'member': member, 'value': msg_count, 'type': 'messages'})
        
        elif self.current_type == 'level':
            title = "⭐ Höchstes Level - Allzeit"
            description = "Nutzer mit dem höchsten Level"
            users_data = self.bot.data.get_guild_data(self.guild_id, "level_users")
            
            for user_id_str, user_data in users_data.items():
                if not user_id_str.isdigit():
                    continue
                member = guild.get_member(int(user_id_str))
                if not member:
                    continue
                
                leaderboard.append({
                    'member': member,
                    'value': user_data.get('level', 0),
                    'xp': user_data.get('xp', 0),
                    'type': 'level'
                })
        
        elif self.current_type == 'streak_current':
            title = "🔥 Längste aktive Streak"
            description = "Aktuelle laufende Aktivitäts-Streaks"
            guild_streaks = self.bot.data.get_guild_data(self.guild_id, "streaks")
            
            for user_id_str, data in guild_streaks.items():
                if not user_id_str.isdigit():
                    continue
                member = guild.get_member(int(user_id_str))
                if not member:
                    continue
                
                current_streak = data.get('current_streak', 0)
                if current_streak > 0:
                    leaderboard.append({'member': member, 'value': current_streak, 'type': 'streak'})
        
        elif self.current_type == 'streak_alltime':
            title = "🏆 Längste Streak (Allzeit)"
            description = "Hall of Fame - Rekord-Streaks"
            guild_streaks = self.bot.data.get_guild_data(self.guild_id, "streaks")
            
            for user_id_str, data in guild_streaks.items():
                if not user_id_str.isdigit():
                    continue
                member = guild.get_member(int(user_id_str))
                if not member:
                    continue
                
                max_streak = data.get('max_streak_ever', 0)
                current_streak = data.get('current_streak', 0)
                
                if max_streak > 0:
                    # Check if the max streak is still running
                    is_active = (current_streak == max_streak and current_streak > 0)
                    leaderboard.append({
                        'member': member,
                        'value': max_streak,
                        'type': 'streak_alltime',
                        'is_active': is_active
                    })

        
        # Sort and limit
        leaderboard.sort(key=lambda x: x['value'], reverse=True)
        leaderboard = leaderboard[:15]  # Top 15 for better display
        
        # Create embed
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blue(),
            timestamp=now
        )
        
        if leaderboard:
            leaderboard_text = ""
            for idx, entry in enumerate(leaderboard, 1):
                medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"`{idx}.`"
                
                if entry['type'] == 'messages':
                    leaderboard_text += f"{medal} **{entry['member'].display_name}** - {entry['value']:,} Nachrichten\n"
                elif entry['type'] == 'level':
                    leaderboard_text += f"{medal} **{entry['member'].display_name}** - Level {entry['value']} ({entry['xp']:,} XP)\n"
                elif entry['type'] == 'streak':
                    leaderboard_text += f"{medal} **{entry['member'].display_name}** - {entry['value']} Tage\n"
                elif entry['type'] == 'streak_alltime':
                    # Show if streak is still active or ended
                    status = "🔥 Läuft" if entry.get('is_active', False) else "⏸️ Beendet"
                    leaderboard_text += f"{medal} **{entry['member'].display_name}** - {entry['value']} Tage ({status})\n"
            
            embed.add_field(name="📊 Rangliste", value=leaderboard_text, inline=False)
        else:
            embed.add_field(
                name="📊 Rangliste",
                value="*Noch keine Daten verfügbar. Sobald Aktivität stattfindet, wird diese Liste automatisch aktualisiert.*",
                inline=False
            )
        
        embed.set_footer(text=f"{guild.name} • Zuletzt aktualisiert")
        
        return embed


class LeaderboardDisplayCog(commands.Cog, name="LeaderboardDisplay"):
    """Cog für interaktive Leaderboard-Anzeige."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.update_leaderboards.start()
    
    def cog_unload(self):
        """Wird aufgerufen, wenn der Cog entladen wird."""
        self.update_leaderboards.cancel()
    
    @tasks.loop(minutes=5)
    async def update_leaderboards(self):
        """Aktualisiert alle aktiven Leaderboard-Anzeigen alle 5 Minuten."""
        await self.bot.wait_until_ready()
        
        for guild in self.bot.guilds:
            leaderboard_config = self.bot.data.get_guild_data(guild.id, "leaderboard_config")
            channel_id = leaderboard_config.get('leaderboard_channel_id')
            message_id = leaderboard_config.get('leaderboard_message_id')
            current_type = leaderboard_config.get('current_leaderboard_type', 'messages')
            
            if not channel_id or not message_id:
                continue
            
            channel = guild.get_channel(channel_id)
            if not channel:
                continue
            
            try:
                message = await channel.fetch_message(message_id)
                view = LeaderboardView(self.bot, guild.id, current_type)
                embed = await view.create_leaderboard_embed()
                await message.edit(embed=embed, view=view)
            except discord.NotFound:
                # Message was deleted, clear the config
                leaderboard_config['leaderboard_message_id'] = None
                self.bot.data.save_guild_data(guild.id, "leaderboard_config", leaderboard_config)
            except Exception as e:
                print(f"Error updating leaderboard for guild {guild.id}: {e}")
    
    async def web_setup_leaderboard(self, guild_id: int, channel_id: int):
        """Erstellt oder aktualisiert die Leaderboard-Nachricht."""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return False, "Server nicht gefunden"
        
        channel = guild.get_channel(channel_id)
        if not channel:
            return False, "Channel nicht gefunden"
        
        leaderboard_config = self.bot.data.get_guild_data(guild_id, "leaderboard_config")
        message_id = leaderboard_config.get('leaderboard_message_id')
        
        view = LeaderboardView(self.bot, guild_id, 'messages')
        embed = await view.create_leaderboard_embed()
        
        try:
            if message_id:
                # Try to update existing message
                try:
                    message = await channel.fetch_message(message_id)
                    await message.edit(embed=embed, view=view)
                    return True, f"Leaderboard in #{channel.name} aktualisiert!"
                except discord.NotFound:
                    # Message was deleted, create new one
                    pass
            
            # Create new message
            message = await channel.send(embed=embed, view=view)
            leaderboard_config['leaderboard_message_id'] = message.id
            leaderboard_config['leaderboard_channel_id'] = channel_id
            leaderboard_config['current_leaderboard_type'] = 'messages'
            self.bot.data.save_guild_data(guild_id, "leaderboard_config", leaderboard_config)
            
            return True, f"Interaktives Leaderboard in #{channel.name} erstellt!"
        
        except Exception as e:
            return False, f"Fehler: {str(e)}"


async def setup(bot: commands.Bot):
    await bot.add_cog(LeaderboardDisplayCog(bot))
