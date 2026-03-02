# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import Embed, Color
from typing import Dict, List, Optional, Any
from datetime import datetime
from utils.log_storage import LogStorage

class LoggingCog(commands.Cog, name="Logging"):
    """Discord Audit Logging System"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log_storage = LogStorage()

    def should_log_event(self, guild_id: int, event_type: str,
                        channel_id: Optional[int] = None,
                        user_id: Optional[int] = None) -> bool:
        """Check if an event should be logged based on configuration."""
        config = self.bot.data.get_guild_data(guild_id, "logging")

        # Check if logging is enabled
        if not config.get("enabled"):
            return False

        # Check if event type is enabled
        if event_type not in config.get("enabled_events", []):
            return False

        # Check ignored channels
        if channel_id and channel_id in config.get("ignored_channels", []):
            return False

        # Check ignored users
        if user_id and user_id in config.get("ignored_users", []):
            return False

        return True

    async def _send_log_embed(self, guild_id: int, embed: Embed) -> None:
        """Send a log embed to the configured log channel."""
        config = self.bot.data.get_guild_data(guild_id, "logging")
        log_channel_id = config.get("log_channel_id")

        if not log_channel_id:
            return

        try:
            channel = self.bot.get_channel(log_channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    # ==================== MESSAGE EVENTS ====================

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        """Log when a message is deleted."""
        if not message.guild or message.author.bot:
            return

        if not self.should_log_event(message.guild.id, "message_delete",
                                     message.channel.id, message.author.id):
            return

        # Create embed
        embed = Embed(title="📝 Nachricht gelöscht", color=Color.red())
        embed.add_field(name="Autor", value=f"{message.author.mention} ({message.author.id})", inline=False)
        embed.add_field(name="Kanal", value=f"{message.channel.mention}", inline=False)

        # Truncate message content if too long
        content = message.content[:1024] if message.content else "*Keine Nachricht*"
        embed.add_field(name="Inhalt", value=content, inline=False)

        embed.set_footer(text=f"User ID: {message.author.id}")
        embed.timestamp = datetime.utcnow()

        # Save to database
        self.log_storage.save_log(message.guild.id, {
            'event_type': 'message_delete',
            'user_id': str(message.author.id),
            'user_name': message.author.name,
            'channel_id': str(message.channel.id),
            'channel_name': message.channel.name,
            'action': f'Deleted message',
            'before_value': message.content[:500],
        })

        # Send embed
        await self._send_log_embed(message.guild.id, embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """Log when a message is edited."""
        if not before.guild or before.author.bot:
            return

        # Ignore insignificant edits (e.g., embed updates)
        if before.content == after.content:
            return

        if not self.should_log_event(before.guild.id, "message_edit",
                                     before.channel.id, before.author.id):
            return

        # Create embed
        embed = Embed(title="✏️ Nachricht bearbeitet", color=Color.orange())
        embed.add_field(name="Autor", value=f"{before.author.mention} ({before.author.id})", inline=False)
        embed.add_field(name="Kanal", value=f"{before.channel.mention}", inline=False)

        before_content = before.content[:512] if before.content else "*Leer*"
        after_content = after.content[:512] if after.content else "*Leer*"

        embed.add_field(name="Vorher", value=before_content, inline=False)
        embed.add_field(name="Nachher", value=after_content, inline=False)

        embed.set_footer(text=f"User ID: {before.author.id}")
        embed.timestamp = datetime.utcnow()

        # Save to database
        self.log_storage.save_log(before.guild.id, {
            'event_type': 'message_edit',
            'user_id': str(before.author.id),
            'user_name': before.author.name,
            'channel_id': str(before.channel.id),
            'channel_name': before.channel.name,
            'action': 'Edited message',
            'before_value': before.content[:500],
            'after_value': after.content[:500],
        })

        # Send embed
        await self._send_log_embed(before.guild.id, embed)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: List[discord.Message]):
        """Log when multiple messages are deleted."""
        if not messages or not messages[0].guild:
            return

        guild = messages[0].guild
        if not self.should_log_event(guild.id, "bulk_message_delete", messages[0].channel.id):
            return

        # Create summary embed
        embed = Embed(title="🗑️ Mehrere Nachrichten gelöscht", color=Color.red())
        embed.add_field(name="Kanal", value=f"{messages[0].channel.mention}", inline=False)
        embed.add_field(name="Anzahl", value=str(len(messages)), inline=True)

        unique_authors = set(msg.author.id for msg in messages)
        embed.add_field(name="Autoren", value=str(len(unique_authors)), inline=True)

        embed.timestamp = datetime.utcnow()

        # Save to database
        self.log_storage.save_log(guild.id, {
            'event_type': 'bulk_message_delete',
            'channel_id': str(messages[0].channel.id),
            'channel_name': messages[0].channel.name,
            'action': f'Deleted {len(messages)} messages',
            'extra_data': {'count': len(messages), 'unique_authors': len(unique_authors)}
        })

        # Send embed
        await self._send_log_embed(guild.id, embed)

    # ==================== MEMBER EVENTS ====================

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Log when a member joins the server."""
        if member.bot:
            return

        guild = member.guild
        if not self.should_log_event(guild.id, "member_join"):
            return

        # Create embed
        embed = Embed(title="👋 Mitglied beigetreten", color=Color.green())
        embed.add_field(name="Mitglied", value=f"{member.mention} ({member.id})", inline=False)
        embed.add_field(name="Account-Alter", value=self._get_account_age(member.created_at), inline=False)

        embed.set_thumbnail(url=member.avatar.url if member.avatar else None)
        embed.timestamp = datetime.utcnow()

        # Save to database
        self.log_storage.save_log(guild.id, {
            'event_type': 'member_join',
            'target_id': str(member.id),
            'target_name': member.name,
            'action': 'Joined server',
        })

        # Send embed
        await self._send_log_embed(guild.id, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Log when a member leaves the server."""
        if member.bot:
            return

        guild = member.guild
        if not self.should_log_event(guild.id, "member_remove"):
            return

        # Create embed
        embed = Embed(title="👋 Mitglied verlassen", color=Color.red())
        embed.add_field(name="Mitglied", value=f"{member.name} ({member.id})", inline=False)
        embed.add_field(name="Rollen", value=", ".join([r.mention for r in member.roles[1:]]) or "Keine", inline=False)

        embed.set_thumbnail(url=member.avatar.url if member.avatar else None)
        embed.timestamp = datetime.utcnow()

        # Save to database
        self.log_storage.save_log(guild.id, {
            'event_type': 'member_remove',
            'target_id': str(member.id),
            'target_name': member.name,
            'action': 'Left server',
            'extra_data': {'roles': [r.id for r in member.roles]}
        })

        # Send embed
        await self._send_log_embed(guild.id, embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        """Log when a member is banned."""
        if user.bot:
            return

        if not self.should_log_event(guild.id, "member_ban"):
            return

        # Create embed
        embed = Embed(title="🔨 Mitglied gebannt", color=Color.red())
        embed.add_field(name="Nutzer", value=f"{user.mention} ({user.id})", inline=False)

        embed.set_thumbnail(url=user.avatar.url if user.avatar else None)
        embed.timestamp = datetime.utcnow()

        # Save to database
        self.log_storage.save_log(guild.id, {
            'event_type': 'member_ban',
            'target_id': str(user.id),
            'target_name': user.name,
            'action': 'Banned',
        })

        # Send embed
        await self._send_log_embed(guild.id, embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        """Log when a member is unbanned."""
        if user.bot:
            return

        if not self.should_log_event(guild.id, "member_unban"):
            return

        # Create embed
        embed = Embed(title="✅ Mitglied entbannt", color=Color.green())
        embed.add_field(name="Nutzer", value=f"{user.mention} ({user.id})", inline=False)

        embed.set_thumbnail(url=user.avatar.url if user.avatar else None)
        embed.timestamp = datetime.utcnow()

        # Save to database
        self.log_storage.save_log(guild.id, {
            'event_type': 'member_unban',
            'target_id': str(user.id),
            'target_name': user.name,
            'action': 'Unbanned',
        })

        # Send embed
        await self._send_log_embed(guild.id, embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Log member updates (nickname, roles, avatar)."""
        guild = after.guild

        # Check Nickname change
        if before.nick != after.nick:
            if not self.should_log_event(guild.id, "member_update_nickname",
                                        user_id=after.id):
                return

            embed = Embed(title="✏️ Spitzname geändert", color=Color.orange())
            embed.add_field(name="Mitglied", value=f"{after.mention} ({after.id})", inline=False)
            embed.add_field(name="Vorher", value=before.nick or "Keine", inline=True)
            embed.add_field(name="Nachher", value=after.nick or "Keine", inline=True)
            embed.timestamp = datetime.utcnow()

            self.log_storage.save_log(guild.id, {
                'event_type': 'member_update_nickname',
                'target_id': str(after.id),
                'target_name': after.name,
                'before_value': before.nick,
                'after_value': after.nick,
            })

            await self._send_log_embed(guild.id, embed)

        # Check Role changes
        added_roles = set(after.roles) - set(before.roles)
        removed_roles = set(before.roles) - set(after.roles)

        if added_roles:
            if not self.should_log_event(guild.id, "member_role_add", user_id=after.id):
                pass
            else:
                embed = Embed(title="➕ Rollen hinzugefügt", color=Color.green())
                embed.add_field(name="Mitglied", value=f"{after.mention} ({after.id})", inline=False)
                roles_str = ", ".join([r.mention for r in added_roles])
                embed.add_field(name="Rollen", value=roles_str, inline=False)
                embed.timestamp = datetime.utcnow()

                self.log_storage.save_log(guild.id, {
                    'event_type': 'member_role_add',
                    'target_id': str(after.id),
                    'target_name': after.name,
                    'action': f'Added {len(added_roles)} role(s)',
                    'extra_data': {'role_ids': [r.id for r in added_roles]}
                })

                await self._send_log_embed(guild.id, embed)

        if removed_roles:
            if not self.should_log_event(guild.id, "member_role_remove", user_id=after.id):
                pass
            else:
                embed = Embed(title="➖ Rollen entfernt", color=Color.red())
                embed.add_field(name="Mitglied", value=f"{after.mention} ({after.id})", inline=False)
                roles_str = ", ".join([r.mention for r in removed_roles])
                embed.add_field(name="Rollen", value=roles_str, inline=False)
                embed.timestamp = datetime.utcnow()

                self.log_storage.save_log(guild.id, {
                    'event_type': 'member_role_remove',
                    'target_id': str(after.id),
                    'target_name': after.name,
                    'action': f'Removed {len(removed_roles)} role(s)',
                    'extra_data': {'role_ids': [r.id for r in removed_roles]}
                })

                await self._send_log_embed(guild.id, embed)

    # ==================== ROLE EVENTS ====================

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        """Log when a role is created."""
        guild = role.guild

        if not self.should_log_event(guild.id, "role_create"):
            return

        # Create embed
        embed = Embed(title="➕ Rolle erstellt", color=Color.green())
        embed.add_field(name="Rolle", value=f"{role.mention}", inline=False)
        embed.add_field(name="Farbe", value=str(role.color), inline=True)
        embed.add_field(name="Hoistbar", value="Ja" if role.hoist else "Nein", inline=True)
        embed.timestamp = datetime.utcnow()

        # Save to database
        self.log_storage.save_log(guild.id, {
            'event_type': 'role_create',
            'target_id': str(role.id),
            'target_name': role.name,
            'action': 'Created role',
            'extra_data': {
                'color': str(role.color),
                'hoist': role.hoist,
                'mentionable': role.mentionable
            }
        })

        # Send embed
        await self._send_log_embed(guild.id, embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        """Log when a role is deleted."""
        guild = role.guild

        if not self.should_log_event(guild.id, "role_delete"):
            return

        # Create embed
        embed = Embed(title="➖ Rolle gelöscht", color=Color.red())
        embed.add_field(name="Rolle", value=role.name, inline=False)
        embed.add_field(name="ID", value=str(role.id), inline=False)
        embed.timestamp = datetime.utcnow()

        # Save to database
        self.log_storage.save_log(guild.id, {
            'event_type': 'role_delete',
            'target_id': str(role.id),
            'target_name': role.name,
            'action': 'Deleted role',
        })

        # Send embed
        await self._send_log_embed(guild.id, embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        """Log when a role is updated."""
        guild = after.guild

        if not self.should_log_event(guild.id, "role_update"):
            return

        changes = []

        if before.name != after.name:
            changes.append(f"Name: `{before.name}` → `{after.name}`")

        if before.color != after.color:
            changes.append(f"Farbe: `{before.color}` → `{after.color}`")

        if not changes:
            return

        # Create embed
        embed = Embed(title="✏️ Rolle geändert", color=Color.orange())
        embed.add_field(name="Rolle", value=f"{after.mention}", inline=False)
        embed.add_field(name="Änderungen", value="\n".join(changes), inline=False)
        embed.timestamp = datetime.utcnow()

        # Save to database
        self.log_storage.save_log(guild.id, {
            'event_type': 'role_update',
            'target_id': str(after.id),
            'target_name': after.name,
            'action': 'Updated role',
            'extra_data': {'changes': changes}
        })

        # Send embed
        await self._send_log_embed(guild.id, embed)

    # ==================== CHANNEL EVENTS ====================

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        """Log when a channel is created."""
        guild = channel.guild

        if not self.should_log_event(guild.id, "channel_create"):
            return

        # Create embed
        channel_type = "Text" if isinstance(channel, discord.TextChannel) else "Voice"
        embed = Embed(title="➕ Kanal erstellt", color=Color.green())
        embed.add_field(name="Kanal", value=f"{channel.mention}", inline=False)
        embed.add_field(name="Typ", value=channel_type, inline=True)
        embed.add_field(name="ID", value=str(channel.id), inline=True)
        embed.timestamp = datetime.utcnow()

        # Save to database
        self.log_storage.save_log(guild.id, {
            'event_type': 'channel_create',
            'target_id': str(channel.id),
            'target_name': channel.name,
            'action': f'Created {channel_type} channel',
        })

        # Send embed
        await self._send_log_embed(guild.id, embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        """Log when a channel is deleted."""
        guild = channel.guild

        if not self.should_log_event(guild.id, "channel_delete"):
            return

        # Create embed
        channel_type = "Text" if isinstance(channel, discord.TextChannel) else "Voice"
        embed = Embed(title="➖ Kanal gelöscht", color=Color.red())
        embed.add_field(name="Kanal", value=f"#{channel.name}", inline=False)
        embed.add_field(name="Typ", value=channel_type, inline=True)
        embed.add_field(name="ID", value=str(channel.id), inline=True)
        embed.timestamp = datetime.utcnow()

        # Save to database
        self.log_storage.save_log(guild.id, {
            'event_type': 'channel_delete',
            'target_id': str(channel.id),
            'target_name': channel.name,
            'action': f'Deleted {channel_type} channel',
        })

        # Send embed
        await self._send_log_embed(guild.id, embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        """Log when a channel is updated."""
        guild = after.guild

        if not self.should_log_event(guild.id, "channel_update"):
            return

        changes = []

        if before.name != after.name:
            changes.append(f"Name: `{before.name}` → `{after.name}`")

        if not changes:
            return

        # Create embed
        embed = Embed(title="✏️ Kanal geändert", color=Color.orange())
        embed.add_field(name="Kanal", value=f"{after.mention}", inline=False)
        embed.add_field(name="Änderungen", value="\n".join(changes), inline=False)
        embed.timestamp = datetime.utcnow()

        # Save to database
        self.log_storage.save_log(guild.id, {
            'event_type': 'channel_update',
            'target_id': str(after.id),
            'target_name': after.name,
            'action': 'Updated channel',
            'extra_data': {'changes': changes}
        })

        # Send embed
        await self._send_log_embed(guild.id, embed)

    # ==================== WEB INTEGRATION ====================

    async def web_get_config(self, guild_id: int) -> Dict[str, Any]:
        """Get logging configuration for web UI."""
        config = self.bot.data.get_guild_data(guild_id, "logging")
        return config

    async def web_set_config(self, guild_id: int, config_data: Dict[str, Any]) -> tuple:
        """Save logging configuration from web UI."""
        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return False, "Server nicht gefunden."

            # Validate log channel
            log_channel_id = config_data.get('log_channel_id')
            if log_channel_id:
                channel = guild.get_channel(log_channel_id)
                if not channel or not isinstance(channel, discord.TextChannel):
                    return False, "Log-Kanal ungültig."

            # Save configuration
            config = self.bot.data.get_guild_data(guild_id, "logging")
            config['enabled'] = True
            config['log_channel_id'] = log_channel_id
            config['enabled_events'] = config_data.get('enabled_events', [])
            config['ignored_channels'] = config_data.get('ignored_channels', [])
            config['ignored_users'] = config_data.get('ignored_users', [])
            config['retention_days'] = config_data.get('retention_days', 30)

            self.bot.data.save_guild_data(guild_id, "logging", config)

            return True, "Logging-Konfiguration gespeichert."

        except Exception as e:
            return False, f"Fehler beim Speichern: {str(e)}"

    # ==================== UTILITIES ====================

    def _get_account_age(self, created_at) -> str:
        """Calculate account age in a readable format."""
        delta = datetime.utcnow() - created_at
        days = delta.days

        if days < 1:
            return "Weniger als 1 Tag"
        elif days == 1:
            return "1 Tag"
        elif days < 7:
            return f"{days} Tage"
        elif days < 30:
            weeks = days // 7
            return f"{weeks} Wochen"
        elif days < 365:
            months = days // 30
            return f"{months} Monate"
        else:
            years = days // 365
            return f"{years} Jahre"


async def setup(bot):
    """Required function to register the cog."""
    await bot.add_cog(LoggingCog(bot))
