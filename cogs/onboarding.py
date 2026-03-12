# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import datetime
from typing import Tuple, Optional, List

class OnboardingCog(commands.Cog, name="Onboarding"):
    """
    Weist Mitgliedern automatisch Rollen zu, wenn sie joinen oder die Discord-Regeln akzeptieren.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """
        Assigns roles immediately when a member joins.
        """
        if member.bot:
            return

        # Check if module is enabled
        guild_config = self.bot.data.get_server_config(member.guild.id)
        if "Onboarding" not in guild_config.get("enabled_cogs", []):
            return

        config = self.bot.data.get_guild_data(member.guild.id, "onboarding")
        if not config.get("enabled"):
            return

        # Immediate roles
        join_role_ids = config.get("join_role_ids", [])
        roles_to_assign = []
        
        for r_id in join_role_ids:
            role = member.guild.get_role(r_id)
            if role:
                roles_to_assign.append(role)

        # Twitch roles if enabled for join
        if config.get("auto_twitch_on_join"):
            twitch_roles = await self._get_all_twitch_roles(member.guild)
            roles_to_assign.extend(twitch_roles)

        if roles_to_assign:
            # Remove duplicates
            roles_to_assign = list(set(roles_to_assign))
            await self._assign_roles(member, roles_to_assign, "Onboarding: Join")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """
        Detects when a member accepts Discord's rules (pending status changes).
        """
        if before.pending == after.pending:
            return

        if not (before.pending and not after.pending):
            return

        if after.bot:
            return

        # Check if module is enabled
        guild_config = self.bot.data.get_server_config(after.guild.id)
        if "Onboarding" not in guild_config.get("enabled_cogs", []):
            return

        config = self.bot.data.get_guild_data(after.guild.id, "onboarding")
        if not config.get("enabled"):
            return

        # Roles for verified members
        role_ids = config.get("role_ids", []) # Legacy/Standard verified roles
        roles_to_assign = []
        
        for r_id in role_ids:
            role = after.guild.get_role(r_id)
            if role:
                roles_to_assign.append(role)

        # Twitch roles if enabled for verification
        if config.get("auto_twitch_on_verify"):
            twitch_roles = await self._get_all_twitch_roles(after.guild)
            roles_to_assign.extend(twitch_roles)

        if roles_to_assign:
            # Remove duplicates
            roles_to_assign = list(set(roles_to_assign))
            await self._assign_roles(after, roles_to_assign, "Onboarding: Verified")

    async def _get_all_twitch_roles(self, guild: discord.Guild) -> List[discord.Role]:
        """Fetches all notification roles from the Twitch module."""
        guild_data = self.bot.data.get_guild_data(guild.id, "streamers")
        streamers = guild_data.get("streamers", {})
        roles = []
        for s_data in streamers.values():
            role_id = s_data.get("notification_role_id")
            if role_id:
                role = guild.get_role(role_id)
                if role:
                    roles.append(role)
        return roles

    async def _assign_roles(self, member: discord.Member, roles_to_assign: List[discord.Role], reason: str):
        """Helper to assign multiple roles safely."""
        guild = member.guild
        bot_member = guild.get_member(self.bot.user.id)
        if not bot_member: return

        bot_top_role = bot_member.top_role
        assignable = [r for r in roles_to_assign if r.position < bot_top_role.position]
        
        if not assignable:
            return

        try:
            await member.add_roles(*assignable, reason=reason)
            await self._log_assignment(guild, member, True, assignable)
        except Exception as e:
            print(f"[Onboarding] Error assigning roles: {e}")
            await self._log_assignment(guild, member, False, assignable, str(e))

    async def _log_assignment(self, guild: discord.Guild, member: discord.Member,
                            success: bool, roles: List[discord.Role], error: Optional[str] = None):
        """Logs role assignment to a configured log channel."""
        config = self.bot.data.get_guild_data(guild.id, "onboarding")
        log_channel_id = config.get("log_channel_id")
        if not log_channel_id: return

        channel = guild.get_channel(log_channel_id)
        if not isinstance(channel, discord.TextChannel): return

        try:
            embed = discord.Embed(
                title="✅ Onboarding: Rollen zugewiesen" if success else "⚠️ Onboarding: Fehler",
                description=f"{member.mention} hat Rollen erhalten ({'Join' if 'Join' in str(error or '') else 'Verifiziert'})." if success else f"Fehler bei {member.mention}",
                color=discord.Color.green() if success else discord.Color.orange(),
                timestamp=datetime.datetime.utcnow()
            )
            if success and roles:
                embed.add_field(name="Rollen", value=", ".join([r.mention for r in roles]), inline=False)
            elif error:
                embed.add_field(name="Fehler", value=error, inline=False)
            
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)
        except: pass

    async def web_set_config(self, guild_id: int, 
                            join_role_ids: List[int],
                            verified_role_ids: List[int],
                            auto_twitch_on_join: bool,
                            auto_twitch_on_verify: bool,
                            log_channel_id: Optional[int]) -> Tuple[bool, str]:
        """Updates the onboarding configuration from the web interface."""
        config = self.bot.data.get_guild_data(guild_id, "onboarding")
        config["enabled"] = True
        config["join_role_ids"] = join_role_ids
        config["role_ids"] = verified_role_ids # compatibility with legacy name
        config["auto_twitch_on_join"] = auto_twitch_on_join
        config["auto_twitch_on_verify"] = auto_twitch_on_verify
        config["log_channel_id"] = log_channel_id

        self.bot.data.save_guild_data(guild_id, "onboarding", config)
        return True, "Onboarding-Einstellungen erfolgreich gespeichert."

    async def web_get_config(self, guild_id: int) -> dict:
        """Retrieves the current onboarding configuration."""
        config = self.bot.data.get_guild_data(guild_id, "onboarding")
        config.setdefault("enabled", False)
        config.setdefault("join_role_ids", [])
        config.setdefault("role_ids", [])
        config.setdefault("auto_twitch_on_join", False)
        config.setdefault("auto_twitch_on_verify", False)
        config.setdefault("log_channel_id", None)
        return config


async def setup(bot):
    """Registers the OnboardingCog with the bot."""
    await bot.add_cog(OnboardingCog(bot))
