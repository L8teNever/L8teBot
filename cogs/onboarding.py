# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import datetime
from typing import Tuple, Optional, List

class OnboardingCog(commands.Cog, name="Onboarding"):
    """
    Weist Mitgliedern automatisch Rollen zu, wenn sie die Discord-Regeln akzeptieren.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """
        Detects when a member accepts Discord's rules (pending status changes).
        Assigns configured roles to verified members.
        """
        # Early returns for efficiency
        if before.pending == after.pending:
            return  # No change in pending status

        if not (before.pending and not after.pending):
            return  # Not the transition we care about (True → False)

        if after.bot:
            return  # Ignore bots

        # Check if module is enabled
        guild_config = self.bot.data.get_server_config(after.guild.id)
        if "Onboarding" not in guild_config.get("enabled_cogs", []):
            return

        # Load onboarding config
        config = self.bot.data.get_guild_data(after.guild.id, "onboarding")
        if not config.get("enabled") or not config.get("role_ids"):
            return

        # Assign roles
        await self._assign_roles_on_verification(after, config)

    async def _assign_roles_on_verification(self, member: discord.Member, config: dict):
        """
        Assigns configured roles to a member after they accept the rules.

        Args:
            member: The Discord member who accepted the rules
            config: The onboarding configuration for this guild
        """
        guild = member.guild
        role_ids = config.get("role_ids", [])

        # Validate and collect roles
        roles_to_assign = []
        missing_roles = []

        for role_id in role_ids:
            role = guild.get_role(role_id)
            if role:
                roles_to_assign.append(role)
            else:
                missing_roles.append(role_id)

        # Log missing roles
        if missing_roles:
            print(f"[Onboarding] Missing roles in {guild.name}: {missing_roles}")

        # If no valid roles, return early
        if not roles_to_assign:
            print(f"[Onboarding] No valid roles to assign for {member.name} in {guild.name}")
            return

        # Check bot permissions and role hierarchy
        bot_member = guild.get_member(self.bot.user.id)
        if not bot_member:
            print(f"[Onboarding] Bot not a member of {guild.name}")
            return

        bot_top_role = bot_member.top_role
        assignable = [r for r in roles_to_assign if r.position < bot_top_role.position]
        blocked = [r for r in roles_to_assign if r.position >= bot_top_role.position]

        # Assign roles
        try:
            if assignable:
                await member.add_roles(*assignable, reason="Onboarding: Rules accepted")
                print(f"[Onboarding] Assigned {len(assignable)} role(s) to {member.name} in {guild.name}")
                await self._log_assignment(guild, member, True, assignable)
            else:
                print(f"[Onboarding] No assignable roles for {member.name} (hierarchy issue)")

        except discord.Forbidden:
            error_msg = "Missing 'Manage Roles' permission"
            print(f"[Onboarding] {error_msg} in {guild.name}")
            await self._log_assignment(guild, member, False, roles_to_assign, error_msg)

        except discord.HTTPException as e:
            error_msg = f"HTTP error: {str(e)}"
            print(f"[Onboarding] {error_msg} in {guild.name}")
            await self._log_assignment(guild, member, False, roles_to_assign, error_msg)

        except discord.NotFound:
            # Member left before we could assign roles
            print(f"[Onboarding] Member {member.id} left {guild.name} before role assignment")
            return

        # Log hierarchy errors
        if blocked:
            error_msg = f"Role hierarchy issue: {', '.join([r.name for r in blocked])}"
            print(f"[Onboarding] {error_msg} in {guild.name}")
            await self._log_assignment(guild, member, False, blocked, error_msg)

    async def _log_assignment(self, guild: discord.Guild, member: discord.Member,
                            success: bool, roles: List[discord.Role], error: Optional[str] = None):
        """
        Logs role assignment to a configured log channel.

        Args:
            guild: The Discord guild
            member: The member who received roles
            success: Whether the assignment was successful
            roles: List of roles assigned
            error: Error message if assignment failed
        """
        config = self.bot.data.get_guild_data(guild.id, "onboarding")
        log_channel_id = config.get("log_channel_id")

        if not log_channel_id:
            return  # No logging configured

        channel = guild.get_channel(log_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            if success:
                embed = discord.Embed(
                    title="✅ Onboarding: Rollen zugewiesen",
                    description=f"{member.mention} hat die Regeln akzeptiert.",
                    color=discord.Color.green()
                )
                if roles:
                    embed.add_field(
                        name="Zugewiesene Rollen",
                        value=", ".join([r.mention for r in roles]),
                        inline=False
                    )
            else:
                embed = discord.Embed(
                    title="⚠️ Onboarding: Fehler",
                    description=f"Fehler bei der Rollenvergabe für {member.mention}",
                    color=discord.Color.orange()
                )
                embed.add_field(name="Fehler", value=error or "Unbekannt", inline=False)

            embed.set_thumbnail(url=member.display_avatar.url)
            embed.timestamp = datetime.datetime.utcnow()
            embed.set_footer(text=f"User ID: {member.id}")

            await channel.send(embed=embed)

        except (discord.Forbidden, discord.HTTPException) as e:
            print(f"[Onboarding] Could not send log message in {guild.name}: {e}")

    async def web_set_config(self, guild_id: int, role_ids: List[int],
                            log_channel_id: Optional[int]) -> Tuple[bool, str]:
        """
        Updates the onboarding configuration from the web interface.

        Args:
            guild_id: The Discord guild ID
            role_ids: List of role IDs to assign
            log_channel_id: Optional channel ID for logging

        Returns:
            Tuple of (success: bool, message: str)
        """
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return False, "Server nicht gefunden."

        if not role_ids:
            return False, "Du musst mindestens eine Rolle auswählen."

        # Validate all roles exist
        valid_roles = []
        invalid_roles = []

        for role_id in role_ids:
            role = guild.get_role(role_id)
            if role:
                valid_roles.append(role_id)
            else:
                invalid_roles.append(role_id)

        if invalid_roles:
            return False, f"Eine oder mehrere Rollen konnten nicht gefunden werden: {invalid_roles}"

        # Validate log channel if provided
        if log_channel_id:
            channel = guild.get_channel(log_channel_id)
            if not channel or not isinstance(channel, discord.TextChannel):
                return False, "Log-Kanal nicht gefunden oder ungültig."

        # Save configuration
        config = self.bot.data.get_guild_data(guild_id, "onboarding")
        config["enabled"] = True
        config["role_ids"] = valid_roles
        config["log_channel_id"] = log_channel_id

        self.bot.data.save_guild_data(guild_id, "onboarding", config)

        role_count = len(valid_roles)
        msg = f"Onboarding konfiguriert: {role_count} Rolle(n) werden bei Regelakzeptanz zugewiesen."
        return True, msg

    async def web_get_config(self, guild_id: int) -> dict:
        """
        Retrieves the current onboarding configuration.

        Args:
            guild_id: The Discord guild ID

        Returns:
            Configuration dictionary
        """
        config = self.bot.data.get_guild_data(guild_id, "onboarding")
        config.setdefault("enabled", False)
        config.setdefault("role_ids", [])
        config.setdefault("log_channel_id", None)
        return config


async def setup(bot):
    """Registers the OnboardingCog with the bot."""
    await bot.add_cog(OnboardingCog(bot))
