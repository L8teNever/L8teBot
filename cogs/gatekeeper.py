# -*- coding: utf-8 -*-
import discord
from discord.ext import commands, tasks
import datetime
from typing import Tuple, Optional

class GatekeeperCog(commands.Cog, name="Gatekeeper"):
    """
    Kickt Mitglieder, die nach einer bestimmten Zeit keine Rolle haben.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_new_members.start()

    def cog_unload(self):
        self.check_new_members.cancel()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
            
        config = self.bot.data.get_guild_data(member.guild.id, "gatekeeper")

        if not config or not config.get("enabled") or not config.get("required_role_id"):
            return

        pending_members = config.setdefault("pending_members", {})
        pending_members[str(member.id)] = datetime.datetime.utcnow().isoformat()
        self.bot.data.save_guild_data(member.guild.id, "gatekeeper", config)

    @tasks.loop(minutes=1)
    async def check_new_members(self):
        await self.bot.wait_until_ready()
        
        for guild in self.bot.guilds:
            config = self.bot.data.get_guild_data(guild.id, "gatekeeper")
            
            if not config.get("enabled") or not config.get("required_role_id"):
                continue

            required_role_id = config["required_role_id"]
            required_role = guild.get_role(required_role_id)
            if not required_role:
                continue

            time_limit = datetime.timedelta(minutes=config.get("time_limit_minutes", 5))
            kick_message = config.get("kick_message", "Du wurdest vom Server entfernt, da du die Verifizierung nicht innerhalb der vorgegebenen Zeit abgeschlossen hast.")
            
            pending_members = config.get("pending_members", {}).copy()
            members_to_remove_from_pending = []

            for member_id_str, join_time_iso in pending_members.items():
                try:
                    member = await guild.fetch_member(int(member_id_str))
                except discord.NotFound:
                    members_to_remove_from_pending.append(member_id_str)
                    continue
                except discord.HTTPException:
                    continue # Konnte Mitglied nicht abrufen, versuche es später erneut

                if required_role in member.roles:
                    members_to_remove_from_pending.append(member_id_str)
                    continue

                join_time = datetime.datetime.fromisoformat(join_time_iso)
                if datetime.datetime.utcnow() - join_time > time_limit:
                    try:
                        await member.kick(reason=kick_message)
                    except discord.Forbidden:
                        print(f"[Gatekeeper] Keine Berechtigung, {member.name} von {guild.name} zu kicken.")
                    except discord.HTTPException as e:
                        print(f"[Gatekeeper] Fehler beim Kicken von {member.name}: {e}")
                    
                    members_to_remove_from_pending.append(member_id_str)

            if members_to_remove_from_pending:
                for member_id_str in members_to_remove_from_pending:
                    if member_id_str in config["pending_members"]:
                        del config["pending_members"][member_id_str]
                self.bot.data.save_guild_data(guild.id, "gatekeeper", config)

    async def web_set_config(self, guild_id: int, role_id: Optional[int], time_limit: int, kick_message: str) -> Tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Server nicht gefunden."
        if not role_id: return False, "Du musst eine Rolle auswählen."
        if not guild.get_role(role_id): return False, f"Rolle mit ID {role_id} nicht gefunden."
        if not 5 <= time_limit <= 1440: return False, "Zeitlimit muss zwischen 5 und 1440 Minuten liegen."

        config = self.bot.data.get_guild_data(guild_id, "gatekeeper")
        config["enabled"] = True
        config["required_role_id"] = role_id
        config["time_limit_minutes"] = time_limit
        config["kick_message"] = kick_message

        self.bot.data.save_guild_data(guild_id, "gatekeeper", config)
        return True, "Gatekeeper-Einstellungen gespeichert und Modul aktiviert."
 
    async def web_reset_config(self, guild_id: int) -> Tuple[bool, str]:
        config = self.bot.data.get_guild_data(guild_id, "gatekeeper")
 
        if not config or not config.get("enabled", False):
            return True, "Gatekeeper war nicht aktiviert. Nichts zu tun."
 
        config["enabled"] = False
        config["pending_members"] = {}
        
        self.bot.data.save_guild_data(guild_id, "gatekeeper", config)
        return True, "Gatekeeper wurde deaktiviert und die Liste der überwachten Mitglieder wurde zurückgesetzt."

    async def web_get_pending_members(self, guild_id: int) -> list:
        guild = self.bot.get_guild(guild_id)
        if not guild: return []

        pending_data = self.bot.data.get_guild_data(guild_id, "gatekeeper").get("pending_members", {})
        result = []
        for member_id_str, join_time_iso in pending_data.items():
            member = guild.get_member(int(member_id_str))
            if member:
                result.append({"id": member.id, "name": member.display_name, "avatar_url": str(member.display_avatar.url), "join_time": join_time_iso})
        return result

async def setup(bot: commands.Bot):
    await bot.add_cog(GatekeeperCog(bot))
