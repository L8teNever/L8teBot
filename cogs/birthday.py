# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
from discord import app_commands, Interaction, ButtonStyle, Embed, Color, TextChannel, Role, Member, TextStyle, Forbidden, HTTPException, NotFound
import datetime
import asyncio
import traceback
from typing import Optional, List, Tuple
from zoneinfo import ZoneInfo

GERMAN_TZ = ZoneInfo("Europe/Berlin")

# --- Hilfsfunktionen ---
def get_adjusted_time():
    """Gibt die aktuelle Zeit für die deutsche Zeitzone zurück."""
    return datetime.datetime.now(GERMAN_TZ)

def validate_birthday_format(date_str):
    """Validiert das Datumsformat (MM-DD)."""
    if not isinstance(date_str, str): return False
    try:
        datetime.datetime.strptime(date_str, "%m-%d")
        parts = date_str.split('-')
        return len(parts) == 2 and 1 <= int(parts[0]) <= 12 and 1 <= int(parts[1]) <= 31
    except (ValueError, TypeError):
        return False

# --- UI-Elemente (Modal & Views) ---
class BirthdayInputModal(Modal, title='Geburtstag hinzufügen/ändern'):
    day_input = TextInput(label='Tag', placeholder='z.B. 25', style=TextStyle.short, required=True, min_length=1, max_length=2)
    month_input = TextInput(label='Monat', placeholder='z.B. 12', style=TextStyle.short, required=True, min_length=1, max_length=2)
    year_input = TextInput(label='Jahr (optional)', placeholder='z.B. 1990', style=TextStyle.short, required=False, min_length=4, max_length=4)

    def __init__(self, bot_instance: commands.Bot):
        super().__init__(timeout=300)
        self.bot = bot_instance

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            day = int(self.day_input.value.strip())
            month = int(self.month_input.value.strip())
            year_str = self.year_input.value.strip()
            year = int(year_str) if year_str else None

            datetime.datetime(year if year else 2000, month, day) # Validierung

            guild_id = interaction.guild.id
            user_id_str = str(interaction.user.id)
            
            # Using DataManager
            data = self.bot.data.get_guild_data(guild_id, "birthday")
            birthdays = data.setdefault("birthdays", {})
            
            birthday_data = {"date": f"{month:02d}-{day:02d}"}
            if year:
                birthday_data["year"] = year

            birthdays[user_id_str] = birthday_data
            self.bot.data.save_guild_data(guild_id, "birthday", data)

            await interaction.followup.send(f"Dein Geburtstag wurde gespeichert!", ephemeral=True)
            cog = self.bot.get_cog('Geburtstage')
            if cog:
                await cog.update_birthday_list_message(interaction.guild)
        except ValueError:
            await interaction.followup.send("Ungültiges Datum. Bitte prüfe deine Eingabe.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send("Ein Fehler ist aufgetreten.", ephemeral=True)
            traceback.print_exc()

class BirthdayListView(View):
    def __init__(self, bot_instance: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot_instance

    @discord.ui.button(label='🎂 Geburtstag hinzufügen/ändern', style=ButtonStyle.success, custom_id='add_birthday_button_persistent')
    async def add_birthday(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(BirthdayInputModal(self.bot))

    @discord.ui.button(label='🗑️ Meinen Geburtstag löschen', style=ButtonStyle.danger, custom_id='remove_birthday_button_persistent')
    async def remove_birthday(self, interaction: Interaction, button: Button):
        guild_id = interaction.guild.id
        user_id_str = str(interaction.user.id)
        
        data = self.bot.data.get_guild_data(guild_id, "birthday")
        birthdays = data.get("birthdays", {})
        
        if birthdays.pop(user_id_str, None):
            self.bot.data.save_guild_data(guild_id, "birthday", data)
            await interaction.response.send_message("Dein Geburtstag wurde entfernt.", ephemeral=True)
            cog = self.bot.get_cog('Geburtstage')
            if cog:
                await cog.update_birthday_list_message(interaction.guild)
        else:
            await interaction.response.send_message("Kein Geburtstag für dich gefunden.", ephemeral=True)

# --- Haupt-Cog ---
class BirthdayCog(commands.Cog, name="Geburtstage"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_birthdays_task.start()

    def cog_unload(self):
        self.check_birthdays_task.cancel()

    # --- Task für tägliche Checks ---
    @tasks.loop(time=datetime.time(hour=0, minute=1, second=0, tzinfo=GERMAN_TZ))
    async def check_birthdays_task(self):
        await self.bot.wait_until_ready()
        today_str = get_adjusted_time().strftime("%m-%d")
        print(f"[{get_adjusted_time()}] Starte täglichen Geburtstags-Check...")

        for guild in self.bot.guilds:
            config = self.bot.data.get_guild_data(guild.id, "birthday")
            birthdays = config.get("birthdays", {})
            role = guild.get_role(config.get("role_id", 0))

            # Rollen von gestern entfernen
            if role:
                for member in guild.members:
                    if role in member.roles and birthdays.get(str(member.id), {}).get("date") != today_str:
                        try: await member.remove_roles(role, reason="Geburtstag vorbei")
                        except (discord.Forbidden, discord.HTTPException): pass

            # Heutige Geburtstagskinder finden
            todays_birthdays_members = []
            for user_id, bday_data in birthdays.items():
                if bday_data.get("date") == today_str:
                    member = guild.get_member(int(user_id))
                    if member:
                        todays_birthdays_members.append(member)
                        if role:
                            try: await member.add_roles(role, reason="Herzlichen Glückwunsch!")
                            except (discord.Forbidden, discord.HTTPException): pass
            
            # Ankündigung senden
            announcement_channel_id = config.get("announcement_channel_id")
            if todays_birthdays_members and announcement_channel_id:
                channel = guild.get_channel(announcement_channel_id)
                if channel:
                    mentions = ", ".join(m.mention for m in todays_birthdays_members)
                    embed = Embed(title="🎂 Herzlichen Glückwunsch zum Geburtstag!", description=f"Alles Gute zum Geburtstag, {mentions}! 🎉", color=Color.gold())
                    try: await channel.send(embed=embed)
                    except (discord.Forbidden, discord.HTTPException): pass
        
        print(f"[{get_adjusted_time()}] Täglicher Geburtstags-Check beendet.")

    # --- Kernfunktion zum Aktualisieren der Liste ---
    async def update_birthday_list_message(self, guild: discord.Guild):
        config = self.bot.data.get_guild_data(guild.id, "birthday")
        channel_id = config.get("list_channel_id")
        message_id = config.get("list_message_id")

        if not channel_id or not message_id: return

        try:
            channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            message = await channel.fetch_message(message_id)
        except (NotFound, Forbidden, HTTPException):
            return

        embed = Embed(title=f"🎂 Geburtstagsliste - {guild.name}", color=Color.gold())
        
        all_birthdays = []
        birthdays_data = config.get("birthdays", {})
        users_to_remove = []  # Track users that no longer exist
        
        for user_id, bday_data in birthdays_data.items():
            member = guild.get_member(int(user_id))
            if not member:
                # User no longer on server or account deleted - mark for removal
                users_to_remove.append(user_id)
                continue
                
            try:
                # Handle new and old format of bday_data
                date_str = None
                year = None
                if isinstance(bday_data, dict):
                    date_str = bday_data.get("date")
                    year = bday_data.get("year")
                elif isinstance(bday_data, str): # Old format compatibility
                    date_str = bday_data
                
                if not date_str or not validate_birthday_format(date_str):
                    continue

                dt_obj = datetime.datetime.strptime(date_str, "%m-%d")
                all_birthdays.append((dt_obj.month, dt_obj.day, member, year))
            except (ValueError, KeyError, AttributeError):
                continue
        
        # Clean up users that no longer exist
        if users_to_remove:
            for user_id in users_to_remove:
                del birthdays_data[user_id]
            self.bot.data.save_guild_data(guild.id, "birthday", config)
            print(f"[Birthday] Cleaned up {len(users_to_remove)} non-existent users from {guild.name}")
        
        all_birthdays.sort()

        if not all_birthdays:
            embed.description = "Noch keine Geburtstage eingetragen!"
        else:
            months = {
                1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
                7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember"
            }
            current_month = -1
            month_lines = []
            for month, day, member, year in all_birthdays:
                if month != current_month:
                    if month_lines:
                        embed.add_field(name=f"📅 {months[current_month]}", value="\n".join(month_lines), inline=False)
                    current_month = month
                    month_lines = []
                year_str = f" ({year})" if year else ""
                month_name = months.get(month, "Unbekannt")
                line = f"**{member.display_name}** → {day:02d}. {month_name}{year_str}"
                month_lines.append(line)
            
            if month_lines:
                embed.add_field(name=f"📅 {months[current_month]}", value="\n".join(month_lines), inline=False)

        embed.set_footer(text=f"Zuletzt aktualisiert: {get_adjusted_time().strftime('%d.%m.%Y %H:%M:%S %Z')}")
        
        try:
            await message.edit(content=None, embed=embed, view=BirthdayListView(self.bot))
        except (NotFound, Forbidden, HTTPException) as e:
            print(f"Fehler beim Bearbeiten der Geburtstagsliste: {e}")

    # --- Web API Methoden (für Flask) ---
    async def web_set_config(self, guild_id: int, list_ch_id: Optional[int], ann_ch_id: Optional[int], role_id: Optional[int]) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."
        
        config = self.bot.data.get_guild_data(guild_id, "birthday")

        # Alte Nachricht löschen, falls vorhanden (auch bei Kanalwechsel)
        old_list_channel_id = config.get('list_channel_id')
        old_list_message_id = config.get('list_message_id')
        if old_list_channel_id and old_list_message_id:
            try:
                old_channel = self.bot.get_channel(old_list_channel_id) or await self.bot.fetch_channel(old_list_channel_id)
                old_msg = await old_channel.fetch_message(old_list_message_id)
                await old_msg.delete()
            except (NotFound, Forbidden, HTTPException):
                pass 

        # Liste Kanal
        if list_ch_id:
            channel = guild.get_channel(list_ch_id)
            if not channel or not isinstance(channel, TextChannel): return False, "Listen-Kanal ungültig."
            config['list_channel_id'] = list_ch_id
            
            try:
                embed = Embed(title=f"🎂 Geburtstagsliste - {guild.name}", description="Wird geladen...", color=Color.gold())
                new_msg = await channel.send(embed=embed, view=BirthdayListView(self.bot))
                config['list_message_id'] = new_msg.id
            except (Forbidden, HTTPException):
                return False, f"Keine Rechte zum Senden im Listen-Kanal {channel.mention}."
        else:
            config['list_channel_id'] = None
            config['list_message_id'] = None

        # Ankündigungskanal
        config['announcement_channel_id'] = ann_ch_id

        # Rolle
        if role_id:
            role = guild.get_role(role_id)
            if not role or guild.me.top_role <= role:
                return False, "Rolle ungültig oder zu hoch in der Hierarchie."
            config['role_id'] = role_id
        else:
            config['role_id'] = None

        self.bot.data.save_guild_data(guild_id, "birthday", config)
        if list_ch_id:
            await self.update_birthday_list_message(guild)
        return True, "Geburtstags-Einstellungen erfolgreich gespeichert."

    async def web_add_birthday(self, guild_id: int, user_id: int, day: int, month: int, year: Optional[int]) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."
        member = guild.get_member(user_id)
        if not member: return False, "Benutzer nicht auf dem Server."

        try:
            datetime.date(year if year else 2000, month, day)
        except ValueError:
            return False, "Ungültiges Datum."
            
        config = self.bot.data.get_guild_data(guild_id, "birthday")
        birthdays = config.setdefault("birthdays", {})
        
        birthdays[str(user_id)] = {"date": f"{month:02d}-{day:02d}"}
        if year:
            birthdays[str(user_id)]["year"] = year

        self.bot.data.save_guild_data(guild_id, "birthday", config)
        await self.update_birthday_list_message(guild)
        return True, f"Geburtstag für {member.display_name} hinzugefügt."

    async def web_remove_birthday(self, guild_id: int, user_id: int) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."
        
        config = self.bot.data.get_guild_data(guild_id, "birthday")
        birthdays = config.get("birthdays", {})
        
        if birthdays.pop(str(user_id), None):
            self.bot.data.save_guild_data(guild_id, "birthday", config)
            await self.update_birthday_list_message(guild)
            return True, f"Geburtstag für Benutzer-ID {user_id} entfernt."
        return False, "Kein Geburtstag für diesen Benutzer gefunden."

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Entfernt den Geburtstag eines Users, wenn er den Server verlässt."""
        guild_id = member.guild.id
        user_id_str = str(member.id)
        
        config = self.bot.data.get_guild_data(guild_id, "birthday")
        birthdays = config.get("birthdays", {})
        
        if user_id_str in birthdays:
            del birthdays[user_id_str]
            self.bot.data.save_guild_data(guild_id, "birthday", config)
            print(f"[Birthday] User {member} (ID: {user_id_str}) hat den Server {member.guild.name} verlassen. Geburtstag entfernt.")
            
            # Liste aktualisieren
            await self.update_birthday_list_message(member.guild)

async def setup(bot: commands.Bot):
    bot.add_view(BirthdayListView(bot))
    await bot.add_cog(BirthdayCog(bot))
