# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import Embed, Color, TextChannel, Forbidden, HTTPException
from typing import Optional, Tuple

class CountingCog(commands.Cog, name="Zählen"):
    """Cog für das Zählspiel."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _get_counting_data(self, guild_id: int):
        return self.bot.data.get_guild_data(guild_id, "counting")

    def _save_counting_data(self, guild_id: int, data):
        self.bot.data.save_guild_data(guild_id, "counting", data)

    def _get_milestones_data(self, guild_id: int):
        return self.bot.data.get_guild_data(guild_id, "milestones")
    
    def _save_milestones_data(self, guild_id: int, data):
        self.bot.data.save_guild_data(guild_id, "milestones", data)

    # Helper to get global milestones (could be in a global file, putting stub here)
    def _get_global_milestones(self):
        # Implementation: Load from a specific global file or config
        # For now, return empty or try to load 'global_milestones.json' via data manager if we had one.
        # We can use the 'default' logic if we migrated it to a 'default' folder or similar.
        # Let's assume we migrated 'default' milestones to a file named 'milestones.json' in 'data/global' or similar.
        # Since we didn't, we'll return empty dict for now or hardcoded defaults.
        return {"numbers": [], "messages": {}}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        guild_id = message.guild.id
        channel_id_str = str(message.channel.id)
        
        data = self._get_counting_data(guild_id)
        config = data.get(channel_id_str)

        if not config:
            return

        try:
            num = int(message.content.strip())
        except ValueError:
            try: await message.delete()
            except (Forbidden, HTTPException): pass
            return

        current_number = config.get("current_number", 0)
        last_user_id = config.get("last_user_id")
        next_number = current_number + 1

        if message.author.id == last_user_id:
            try:
                await message.delete()
                await message.channel.send(f"{message.author.mention}, du kannst nicht zweimal hintereinander zählen!", delete_after=5)
            except (Forbidden, HTTPException): pass
            return

        if num == next_number:
            config["current_number"] = num
            config["last_user_id"] = message.author.id
            
            # Milestone-Check
            num_str = str(num)
            guild_milestones_config = self._get_milestones_data(guild_id)
            milestone_message_template = None

            # 1. Server-spezifischen Milestone prüfen
            if num in guild_milestones_config.get("numbers", []):
                milestone_message_template = guild_milestones_config.get("messages", {}).get(num_str)
            else:
                # 2. Global Defaults
                # For now using empty defaults as discussed
                global_milestones = self._get_global_milestones()
                is_default_milestone = num in global_milestones.get("numbers", [])
                is_disabled_by_guild = num in guild_milestones_config.get("disabled_defaults", [])
                
                if is_default_milestone and not is_disabled_by_guild:
                    milestone_message_template = global_milestones.get("messages", {}).get(num_str)

            if milestone_message_template:
                milestone_message = milestone_message_template.replace("{user}", message.author.mention).replace("{number}", str(num))
                embed = Embed(title="🏆 Meilenstein erreicht!", description=milestone_message, color=Color.gold())
                try:
                    await message.channel.send(embed=embed)
                except (Forbidden, HTTPException): pass

            self._save_counting_data(guild_id, data)
            try:
                await message.add_reaction("✅")
            except (Forbidden, HTTPException): pass
        else:
            try:
                await message.delete()
                await message.channel.send(f"{message.author.mention}, falsche Zahl! Die nächste Zahl ist {next_number}.", delete_after=5)
            except (Forbidden, HTTPException): pass

    # --- Web API Methoden ---
    async def web_set_channel(self, guild_id: int, channel_id: int) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, TextChannel): return False, "Kanal nicht gefunden oder kein Textkanal."

        data = self._get_counting_data(guild_id)
        channel_id_str = str(channel_id)
        data[channel_id_str] = {"current_number": 0, "last_user_id": None, "slowmode": 1}
        
        try:
            await channel.edit(slowmode_delay=1)
        except (Forbidden, HTTPException):
            return False, "Konnte Slowmode nicht setzen (Berechtigung fehlt)."
            
        self._save_counting_data(guild_id, data)
        return True, f"Kanal {channel.mention} ist jetzt ein Zähl-Kanal."

    async def web_remove_channel(self, guild_id: int, channel_id: int) -> Tuple[bool, str]: # Added guild_id
        data = self._get_counting_data(guild_id)
        channel_id_str = str(channel_id)
        if channel_id_str in data:
            del data[channel_id_str]
            self._save_counting_data(guild_id, data)
            return True, f"Kanal (ID: {channel_id}) ist kein Zähl-Kanal mehr."
        return False, "Kanal war kein Zähl-Kanal."

    async def web_set_count(self, guild_id: int, channel_id: int, number: int) -> Tuple[bool, str]: # Added guild_id
        data = self._get_counting_data(guild_id)
        channel_id_str = str(channel_id)
        if channel_id_str in data:
            data[channel_id_str]["current_number"] = number
            data[channel_id_str]["last_user_id"] = None
            self._save_counting_data(guild_id, data)
            return True, f"Zählstand auf {number} gesetzt."
        return False, "Kanal ist kein Zähl-Kanal."
        
    async def web_set_slowmode(self, guild_id: int, channel_id: int, seconds: int) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, TextChannel): return False, "Kanal nicht gefunden."
        
        data = self._get_counting_data(guild_id)
        channel_id_str = str(channel_id)
        if channel_id_str not in data:
            return False, "Dies ist kein Zähl-Kanal."
            
        if not 0 <= seconds <= 21600:
            return False, "Slowmode muss zwischen 0 und 21600 liegen."
            
        try:
            await channel.edit(slowmode_delay=seconds)
            data[channel_id_str]['slowmode'] = seconds
            self._save_counting_data(guild_id, data)
            return True, f"Slowmode für {channel.mention} auf {seconds}s gesetzt."
        except (Forbidden, HTTPException):
            return False, "Konnte Slowmode nicht setzen (Berechtigung fehlt)."

    async def web_add_milestone(self, guild_id: int, number: int, message: str) -> Tuple[bool, str]:
        if number <= 0: return False, "Zahl muss positiv sein."
        
        data = self._get_milestones_data(guild_id)
        # Ensure default structure
        if "numbers" not in data: data["numbers"] = []
        if "messages" not in data: data["messages"] = {}
        if "disabled_defaults" not in data: data["disabled_defaults"] = []

        if number not in data["numbers"]:
            data["numbers"].append(number)
            data["numbers"].sort()
            
        data["messages"][str(number)] = message
        
        self._save_milestones_data(guild_id, data)
        return True, f"Server-spezifischer Meilenstein für die Zahl {number} hinzugefügt/aktualisiert."

    async def web_remove_milestone(self, guild_id: int, number: int) -> Tuple[bool, str]:
        data = self._get_milestones_data(guild_id)
        
        removed = False
        if number in data.get("numbers", []):
            data["numbers"].remove(number)
            removed = True
        if str(number) in data.get("messages", {}):
            del data["messages"][str(number)]
            removed = True
            
        if removed:
            self._save_milestones_data(guild_id, data)
            return True, f"Server-spezifischer Meilenstein für die Zahl {number} entfernt."
        
        return False, "Kein server-spezifischer Meilenstein für diese Zahl gefunden."

    async def web_toggle_default_milestone(self, guild_id: int, number: int) -> Tuple[bool, str]:
        global_milestones = self._get_global_milestones()
        if number not in global_milestones.get("numbers", []):
            return False, "Dies ist kein gültiger Standard-Meilenstein."

        data = self._get_milestones_data(guild_id)
        if "disabled_defaults" not in data: data["disabled_defaults"] = []
        disabled_list = data["disabled_defaults"]

        if number in disabled_list:
            disabled_list.remove(number)
            action_text = "aktiviert"
        else:
            disabled_list.append(number)
            action_text = "deaktiviert"
        
        self._save_milestones_data(guild_id, data)
        return True, f"Standard-Meilenstein für {number} wurde für diesen Server {action_text}."

async def setup(bot: commands.Bot):
    await bot.add_cog(CountingCog(bot))
