# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
from discord import app_commands, Embed, Color, Member, Interaction, TextChannel, ButtonStyle, utils
import datetime
import heapq
from typing import Optional, Dict, Any, List, Tuple

# --- Standardwerte ---
DEFAULT_XP_PER_MESSAGE = 10
DEFAULT_COOLDOWN_SECONDS = 60
DEFAULT_DAILY_XP_AMOUNT = 50
DEFAULT_XP_FORMULA_BASE = 100
DEFAULT_XP_FORMULA_INCREMENT = 50
BOOST_MULTIPLIERS = {1: 1.25, 2: 1.5, 3: 2.0}

class LevelSystemCog(commands.Cog, name="Level-System"):
    """Cog für das Level-System, basierend auf der bereitgestellten Logik."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.user_message_cooldowns: Dict[int, datetime.datetime] = {}
        self.daily_xp_task.start()

    def cog_unload(self):
        self.daily_xp_task.cancel()

    async def cog_check(self, ctx: commands.Context) -> bool:
        """Prüft, ob der Cog für diesen Server aktiviert ist."""
        if not ctx.guild:
            return False
        config = self.bot.data.get_server_config(ctx.guild.id)
        return self.qualified_name in config.get('enabled_cogs', [])

    # --- Kernlogik ---
    def _get_guild_config(self, guild_id: int) -> Dict[str, Any]:
        return self.bot.data.get_guild_data(guild_id, "level_config")
    
    def _save_guild_config(self, guild_id: int, data: Dict[str, Any]):
        self.bot.data.save_guild_data(guild_id, "level_config", data)

    def _get_users_data(self, guild_id: int) -> Dict[str, Any]:
        return self.bot.data.get_guild_data(guild_id, "level_users")

    def _save_users_data(self, guild_id: int, data: Dict[str, Any]):
        self.bot.data.save_guild_data(guild_id, "level_users", data)

    def _get_user_data(self, guild_id: int, user_id: int, users_data: Dict[str, Any] = None) -> Dict[str, Any]:
        if users_data is None:
            users_data = self._get_users_data(guild_id)
        return users_data.setdefault(str(user_id), {
            "xp": 0, "level": 0, "initial_nachrichten_xp": 0,
            "initial_taegliche_xp": 0, "live_nachrichten_xp": 0, "live_taegliche_xp": 0,
            "manuell_veraenderte_xp": 0, "gesamt_xp": 0, "current_level": 0
        })
    
    def _recalculate_total_xp(self, user_data: Dict[str, Any]):
        user_data["gesamt_xp"] = sum(user_data.get(key, 0) for key in [
            "initial_nachrichten_xp", "initial_taegliche_xp", 
            "live_nachrichten_xp", "live_taegliche_xp", "manuell_veraenderte_xp"
        ])
        user_data["xp"] = user_data["gesamt_xp"] # Alias für Kompatibilität

    def _get_xp_for_level(self, level: int, guild_config: Dict[str, Any]) -> int:
        if level <= 0: return 0
        custom_thresholds = guild_config.get("level_xp_thresholds", {})
        if str(level) in custom_thresholds:
            return custom_thresholds[str(level)]
        
        base = guild_config.get("xp_formula_base", DEFAULT_XP_FORMULA_BASE)
        increment = guild_config.get("xp_formula_increment", DEFAULT_XP_FORMULA_INCREMENT)
        return int(5 * (level ** 2) + (base - 5) * level + increment * (level * (level - 1) / 2))

    def _get_boost_multiplier(self, member: discord.Member, guild_config: Dict[str, Any]) -> float:
        if not isinstance(member, discord.Member): return 1.0
        highest_multiplier = 1.0
        member_role_ids = {role.id for role in member.roles}
        for i in range(1, 4):
            role_id = guild_config.get(f"boost_role_tier{i}_id")
            if role_id and role_id in member_role_ids:
                highest_multiplier = max(highest_multiplier, BOOST_MULTIPLIERS[i])
        return highest_multiplier

    # --- Slash Commands ---
    @app_commands.command(name="rank", description="Zeigt deinen oder den Rang eines anderen Benutzers an.")
    async def rank(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        guild_id = interaction.guild.id
        server_config = self.bot.data.get_server_config(guild_id)
        
        is_cog_enabled = self.qualified_name in server_config.get('enabled_cogs', [])
        if not is_cog_enabled:
            await interaction.response.send_message("Das Level-System ist für diesen Server deaktiviert.", ephemeral=True)
            return

        is_command_enabled = server_config.get('cogs', {}).get(self.qualified_name, {}).get('commands', {}).get('rank', True)
        if not is_command_enabled:
            await interaction.response.send_message("Dieser Befehl ist auf diesem Server deaktiviert.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        
        target_member = member or interaction.user
        guild_config = self._get_guild_config(guild_id)
        users_data = self._get_users_data(guild_id)
        user_data = self._get_user_data(guild_id, target_member.id, users_data)
        
        current_level = user_data.get("level", 0)
        current_xp = user_data.get("xp", 0)
        
        xp_for_current_level = self._get_xp_for_level(current_level, guild_config)
        xp_for_next_level = self._get_xp_for_level(current_level + 1, guild_config)
        
        xp_in_current_level = current_xp - xp_for_current_level
        xp_needed_for_next_level_up = xp_for_next_level - xp_for_current_level
        
        progress = 0
        if xp_needed_for_next_level_up > 0:
            progress = round((xp_in_current_level / xp_needed_for_next_level_up) * 100, 2)
            if progress > 100: progress = 100
            
        embed = discord.Embed(title=f"Rang für {target_member.display_name}", color=target_member.color)
        embed.set_thumbnail(url=target_member.display_avatar.url)
        embed.add_field(name="Level", value=str(current_level), inline=True)
        embed.add_field(name="Gesamt-XP", value=f"{current_xp:,}", inline=True)
        
        if xp_for_next_level > current_xp:
            embed.add_field(name="Fortschritt zum nächsten Level", value=f"{xp_in_current_level:,} / {xp_needed_for_next_level_up:,} XP ({progress}%)", inline=False)
        else:
            embed.add_field(name="Fortschritt", value="Maximales Level erreicht oder nächstes Level nicht definiert.", inline=False)
            
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="leaderboard", description="Zeigt die Top 10 der Level-Rangliste des Servers an.")
    async def leaderboard(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        server_config = self.bot.data.get_server_config(guild_id)
        
        is_cog_enabled = self.qualified_name in server_config.get('enabled_cogs', [])
        if not is_cog_enabled:
            await interaction.response.send_message("Das Level-System ist für diesen Server deaktiviert.", ephemeral=True)
            return

        is_command_enabled = server_config.get('cogs', {}).get(self.qualified_name, {}).get('commands', {}).get('leaderboard', True)
        if not is_command_enabled:
            await interaction.response.send_message("Dieser Befehl ist auf diesem Server deaktiviert.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        
        guild_users_data = self._get_users_data(guild_id)
        if not guild_users_data:
            return await interaction.followup.send("Für diesen Server sind keine Level-Daten vorhanden.")
            
        # Effizient die Top 10 Benutzer ermitteln, ohne die gesamte Liste zu sortieren
        top_10_users = heapq.nlargest(10, guild_users_data.items(), key=lambda item: item[1].get("xp", 0))

        if not top_10_users:
            return await interaction.followup.send("Es gibt noch keine Benutzer mit XP auf diesem Server.")

        guild = interaction.guild
        embed = Embed(title=f"🏆 Top 10 Leaderboard - {guild.name}", color=Color.blue())
        
        leaderboard_entries = []
        guild_config = self._get_guild_config(guild.id)

        for idx, (user_id_str, user_data_dict) in enumerate(top_10_users):
            member = guild.get_member(int(user_id_str))
            
            level = user_data_dict.get("level", 0)
            xp = user_data_dict.get("xp", 0)
            rank = idx + 1
            
            rank_display = f"`#{rank}`"
            if rank == 1: rank_display = "🥇"
            elif rank == 2: rank_display = "🥈"
            elif rank == 3: rank_display = "🥉"
            
            name_display = f"**{discord.utils.escape_markdown(member.display_name)}**" if member else f"Unbekannter Benutzer ({user_id_str})"
            
            boost_info = ""
            if member:
                boost_multiplier = self._get_boost_multiplier(member, guild_config)
                if boost_multiplier > 1.0:
                    boost_info = f" ✨ ({boost_multiplier}x Boost)"

            entry = f"{rank_display} {name_display}{boost_info}\n└ Level {level} • {xp:,} XP"
            leaderboard_entries.append(entry)
        
        embed.description = "\n".join(leaderboard_entries)
        embed.set_footer(text="Zeigt die Top 10 Benutzer nach XP an.")
        
        await interaction.followup.send(embed=embed)

    async def _check_level_up(self, member: discord.Member, user_data: Dict[str, Any]):
        guild_config = self._get_guild_config(member.guild.id)
        current_level = user_data.get("level", 0)
        total_xp = user_data.get("xp", 0)
        
        new_level = current_level
        # Level Up
        while True:
            xp_needed = self._get_xp_for_level(new_level + 1, guild_config)
            if xp_needed > 0 and total_xp >= xp_needed:
                new_level += 1
            else:
                break
        # Level Down
        while new_level > 0:
            xp_needed = self._get_xp_for_level(new_level, guild_config)
            if total_xp < xp_needed:
                new_level -= 1
            else:
                break
        
        if new_level != current_level:
            user_data["level"] = new_level
            await self._update_roles(member, new_level, guild_config)
            
            log_channel_id = guild_config.get("log_channel_id")
            if log_channel_id:
                log_channel = member.guild.get_channel(log_channel_id)
                if log_channel:
                    try:
                        await log_channel.send(f"🎉 Herzlichen Glückwunsch {member.mention}, du hast Level {new_level} erreicht!")
                    except discord.Forbidden: pass
    
    async def _update_roles(self, member: discord.Member, new_level: int, guild_config: Dict[str, Any]):
        if not member.guild.me.guild_permissions.manage_roles:
            print(f"Fehler: Bot hat keine Rechte zum Rollen-Management in {member.guild.name} für {member.display_name}")
            return

        level_roles = guild_config.get("level_roles", {})
        
        # 1. Finde die höchste Rolle, die der Benutzer haben sollte.
        highest_role_to_have = None
        highest_level_for_role = -1
        for level_str, role_id in level_roles.items():
            level = int(level_str)
            if highest_level_for_role < level <= new_level:
                role = member.guild.get_role(role_id)
                if role and member.guild.me.top_role > role:
                    highest_level_for_role = level
                    highest_role_to_have = role

        # 2. Bestimme, welche Rollen hinzugefügt und entfernt werden sollen.
        roles_to_add = []
        roles_to_remove = []
        
        all_level_role_ids = set(level_roles.values())

        for role in member.roles:
            # Wenn der Benutzer eine Level-Rolle hat...
            if role.id in all_level_role_ids:
                # ...und es nicht die höchste ist, die er haben sollte, entferne sie.
                if not highest_role_to_have or role.id != highest_role_to_have.id:
                    roles_to_remove.append(role)

        # Wenn es eine höchste Rolle gibt und der Benutzer sie nicht hat, füge sie hinzu.
        if highest_role_to_have and highest_role_to_have not in member.roles:
            roles_to_add.append(highest_role_to_have)

        try:
            if roles_to_add:
                await member.add_roles(*roles_to_add, reason=f"Level-Up zu Level {new_level}")
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason=f"Level-Up zu Level {new_level}")
        except discord.HTTPException as e:
            print(f"HTTP Fehler beim Rollen-Update für {member.display_name}: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild: return
        server_config = self.bot.data.get_server_config(message.guild.id)
        if self.qualified_name not in server_config.get('enabled_cogs', []): return
        
        guild_config = self._get_guild_config(message.guild.id)
        no_xp_roles = guild_config.get("no_xp_roles", [])
        if any(role.id in no_xp_roles for role in message.author.roles): return

        user_id = message.author.id
        now = datetime.datetime.now(datetime.timezone.utc)
        
        cooldown = guild_config.get("xp_cooldown_seconds", DEFAULT_COOLDOWN_SECONDS)
        last_message_time = self.user_message_cooldowns.get(user_id)
        if last_message_time and (now - last_message_time).total_seconds() < cooldown: return
            
        self.user_message_cooldowns[user_id] = now
        
        xp_to_add = guild_config.get("xp_per_message", DEFAULT_XP_PER_MESSAGE)
        boost = self._get_boost_multiplier(message.author, guild_config)
        final_xp = round(xp_to_add * boost)

        users_data = self._get_users_data(message.guild.id)
        user_data = self._get_user_data(message.guild.id, user_id, users_data)
        user_data["live_nachrichten_xp"] = user_data.get("live_nachrichten_xp", 0) + final_xp
        user_data["letzte_nachricht_xp_timestamp"] = now.isoformat()
        
        self._recalculate_total_xp(user_data)
        await self._check_level_up(message.author, user_data)
        self._save_users_data(message.guild.id, users_data)

    @tasks.loop(time=datetime.time(hour=0, minute=5, tzinfo=datetime.timezone.utc))
    async def daily_xp_task(self):
        await self.bot.wait_until_ready()
        today_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')
        print(f"Starte tägliche XP-Vergabe für {today_str}...")

        for guild in self.bot.guilds:
            server_config = self.bot.data.get_server_config(guild.id)
            if self.qualified_name not in server_config.get('enabled_cogs', []): continue
            
            guild_config = self._get_guild_config(guild.id)
            daily_xp_base = guild_config.get("daily_xp_amount", DEFAULT_DAILY_XP_AMOUNT)
            
            if daily_xp_base > 0:
                guild_users_data = self._get_users_data(guild.id)
                for member in guild.members:
                    if not member.bot:
                        user_data = self._get_user_data(guild.id, member.id, guild_users_data) 
                        
                        # Prüfen, ob die täglichen XP für heute bereits vergeben wurden
                        if user_data.get("last_daily_xp_date") == today_str:
                            continue

                        boost = self._get_boost_multiplier(member, guild_config)
                        final_daily_xp = round(daily_xp_base * boost)

                        user_data["live_taegliche_xp"] = user_data.get("live_taegliche_xp", 0) + final_daily_xp
                        user_data["last_daily_xp_date"] = today_str # Datum der Vergabe speichern
                        
                        self._recalculate_total_xp(user_data)
                        await self._check_level_up(member, user_data)
                
                # Einmal pro Gilde speichern, nachdem alle Mitglieder bearbeitet wurden
                self._save_users_data(guild.id, guild_users_data)
        print("Tägliche XP-Vergabe beendet.")

    # --- Web API Methoden ---
    async def web_get_all_user_stats(self, guild_id: int) -> List[Dict[str, Any]]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return []
        guild_users_data = self._get_users_data(guild_id)
        all_stats = []
        for user_id_str, data in guild_users_data.items():
            member = guild.get_member(int(user_id_str))
            if member:
                stats = data.copy()
                stats["member"] = member
                all_stats.append(stats)
        all_stats.sort(key=lambda x: x.get("gesamt_xp", 0), reverse=True)
        return all_stats

    async def web_set_config(self, guild_id: int, **kwargs) -> Tuple[bool, str]:
        guild_config = self._get_guild_config(guild_id)
        for key, value in kwargs.items():
            guild_config[key] = value
        self._save_guild_config(guild_id, guild_config)
        return True, "Konfiguration gespeichert."

    async def web_manage_role_list(self, guild_id: int, list_name: str, action: str, role_id: int) -> Tuple[bool, str]:
        guild_config = self._get_guild_config(guild_id)
        role_list = guild_config.setdefault(list_name, [])
        if action == "add":
            if role_id not in role_list:
                role_list.append(role_id)
                self._save_guild_config(guild_id, guild_config)
                return True, "Rolle hinzugefügt."
            return False, "Rolle ist bereits in der Liste."
        elif action == "remove":
            if role_id in role_list:
                role_list.remove(role_id)
                self._save_guild_config(guild_id, guild_config)
                return True, "Rolle entfernt."
            return False, "Rolle nicht in der Liste gefunden."
        return False, "Unbekannte Aktion."

    async def web_manage_level_roles(self, guild_id: int, action: str, level: int, role_id: Optional[int] = None) -> Tuple[bool, str]:
        guild_config = self._get_guild_config(guild_id)
        level_roles = guild_config.setdefault("level_roles", {})
        level_str = str(level)
        if action == "add":
            if not role_id: return False, "Keine Rolle angegeben."
            level_roles[level_str] = role_id
            self._save_guild_config(guild_id, guild_config)
            return True, f"Rolle für Level {level} gesetzt."
        elif action == "remove":
            if level_str in level_roles:
                del level_roles[level_str]
                self._save_guild_config(guild_id, guild_config)
                return True, f"Rolle für Level {level} entfernt."
            return False, "Keine Rolle für dieses Level gefunden."
        return False, "Unbekannte Aktion."

    async def web_manage_custom_xp(self, guild_id: int, action: str, level: int, xp: Optional[int] = None) -> Tuple[bool, str]:
        guild_config = self._get_guild_config(guild_id)
        thresholds = guild_config.setdefault("level_xp_thresholds", {})
        level_str = str(level)
        if action == "add":
            if xp is None or xp < 0: return False, "Ungültige XP-Anzahl."
            thresholds[level_str] = xp
            self._save_guild_config(guild_id, guild_config)
            return True, f"Benötigte XP für Level {level} auf {xp} gesetzt."
        elif action == "remove":
            if level_str in thresholds:
                del thresholds[level_str]
                self._save_guild_config(guild_id, guild_config)
                return True, f"Benutzerdefinierte XP für Level {level} entfernt."
            return False, "Keine benutzerdefinierten XP für dieses Level gefunden."
        return False, "Unbekannte Aktion."

    async def _sync_xp_for_guild(self, guild: discord.Guild, force: bool, max_msgs: Optional[int]):
        print(f"Starte XP Sync für Gilde {guild.name}...")
        guild_config = self._get_guild_config(guild.id)
        xp_per_msg = guild_config.get("xp_per_message", DEFAULT_XP_PER_MESSAGE)
        daily_xp = guild_config.get("daily_xp_amount", DEFAULT_DAILY_XP_AMOUNT)
        start_time = datetime.datetime.now(datetime.timezone.utc)
        
        users_data = self._get_users_data(guild.id)

        for member in guild.members:
            if member.bot: continue
            
            user_data = self._get_user_data(guild.id, member.id, users_data) 
            if user_data.get("beitrittsdatum_fuer_sync_referenz") and not force: continue

            if force:
                user_data["initial_nachrichten_xp"] = 0
                user_data["initial_taegliche_xp"] = 0
                user_data["live_nachrichten_xp"] = 0
                user_data["live_taegliche_xp"] = 0
                user_data["manuell_veraenderte_xp"] = 0

            if member.joined_at:
                days_on_server = (start_time - member.joined_at).days
                if days_on_server > 0:
                    user_data["initial_taegliche_xp"] = days_on_server * daily_xp
                user_data["beitrittsdatum_fuer_sync_referenz"] = member.joined_at.isoformat()
            
            msg_count = 0
            if xp_per_msg > 0:
                for channel in guild.text_channels:
                    if channel.permissions_for(guild.me).read_message_history:
                        try:
                            async for msg in channel.history(limit=max_msgs, after=member.joined_at):
                                if msg.author.id == member.id:
                                    msg_count += 1
                        except (discord.Forbidden, discord.HTTPException):
                            continue
            user_data["initial_nachrichten_xp"] = msg_count * xp_per_msg
            
            self._recalculate_total_xp(user_data)
            await self._check_level_up(member, user_data)
        
        self._save_users_data(guild.id, users_data)
        print(f"XP Sync für Gilde {guild.name} beendet.")

    async def web_trigger_sync(self, guild_id: int, force: bool, max_msgs: Optional[int]) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."
        self.bot.loop.create_task(self._sync_xp_for_guild(guild, force, max_msgs))
        return True, "XP-Synchronisation im Hintergrund gestartet. Dies kann einige Zeit dauern."
        
    async def web_set_user_xp(self, guild_id: int, user_id: int, xp: int, level: int) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."
        member = guild.get_member(user_id)
        if not member: return False, "Benutzer nicht auf dem Server gefunden."
        
        if xp < 0 or level < 0: return False, "XP und Level dürfen nicht negativ sein."
            
        users_data = self._get_users_data(guild.id)
        user_data = self._get_user_data(guild.id, user_id, users_data)
        user_data["xp"] = xp
        user_data["level"] = level
        
        await self._check_level_up(member, user_data)
        self._save_users_data(guild.id, users_data)
        return True, f"XP und Level für Benutzer {member.display_name} erfolgreich gesetzt."

    async def web_toggle_command(self, guild_id: int, command_name: str) -> Tuple[bool, str]:
        server_config = self.bot.data.get_server_config(guild_id)
        
        guild_cogs_config = server_config.setdefault('cogs', {})
        level_config = guild_cogs_config.setdefault(self.qualified_name, {})
        commands_config = level_config.setdefault('commands', {})

        current_status = commands_config.get(command_name, True)
        
        new_status = not current_status
        commands_config[command_name] = new_status
        
        self.bot.data.save_server_config(guild_id, server_config)
        
        status_text = 'aktiviert' if new_status else 'deaktiviert'
        return True, f"Befehl `/{command_name}` wurde erfolgreich {status_text}."

    async def web_get_paginated_leaderboard(self, guild_id: int, page: int, per_page: int) -> Dict[str, Any]:
        """Gibt einen Ausschnitt des Leaderboards zurück für die Web-Ansicht."""
        guild = self.bot.get_guild(guild_id)
        if not guild: return {"error": "Guild not found"}

        guild_users_data = self._get_users_data(guild_id)
        if not guild_users_data:
            return {"data": [], "total": 0, "page": page, "pages": 0}

        # Konvertiere in Liste und sortiere
        sorted_users = sorted(guild_users_data.items(), key=lambda item: item[1].get("xp", 0), reverse=True)
        total_users = len(sorted_users)
        
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        
        page_items = sorted_users[start_index:end_index]
        
        result_data = []
        for rank_offset, (user_id_str, user_data) in enumerate(page_items):
            member = guild.get_member(int(user_id_str))
            
            # Versuche Avatar URL zu holen, Fallback auf Default
            avatar_url = str(member.display_avatar.url) if member else "https://cdn.discordapp.com/embed/avatars/0.png"
            member_name = member.display_name if member else f"User {user_id_str}"
            
            result_data.append({
                "rank": start_index + rank_offset + 1,
                "name": member_name,
                "avatar_url": avatar_url,
                "level": user_data.get("level", 0),
                "xp": user_data.get("xp", 0)
            })

        return {
            "data": result_data,
            "total": total_users,
            "page": page,
            "per_page": per_page,
            "pages": (total_users + per_page - 1) // per_page
        }

async def setup(bot: commands.Bot):
    await bot.add_cog(LevelSystemCog(bot))
