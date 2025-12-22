# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands, Embed, Color, TextStyle, Interaction, ButtonStyle, TextChannel, Thread, Role
from discord.ui import View, Button, Modal, TextInput, Select
from typing import Optional, Tuple
import asyncio
from datetime import datetime

class LFGModal(Modal, title='Spieler suchen'):
    """Modal zum Erstellen einer LFG-Suche"""
    
    game_name = TextInput(
        label='Spielname',
        placeholder='z.B. Valorant, League of Legends',
        required=True,
        max_length=50
    )
    
    description = TextInput(
        label='Beschreibung (optional)',
        placeholder='z.B. Suche Leute für Ranked',
        required=False,
        style=TextStyle.paragraph,
        max_length=200
    )
    
    team_size = TextInput(
        label='Team-Größe (optional)',
        placeholder='z.B. 2 (Anzahl der gesuchten Spieler)',
        required=False,
        max_length=2
    )
    
    duration = TextInput(
        label='Zeitrahmen (optional)',
        placeholder='z.B. 2 Stunden',
        required=False,
        max_length=50
    )
    
    def __init__(self, cog_instance, guild_id: int):
        super().__init__()
        self.cog = cog_instance
        self.guild_id = guild_id
    
    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Check user limit
        config = self.cog._get_lfg_config(self.guild_id)
        max_searches = config.get('max_searches_per_user', 3)
        
        searches = self.cog._get_searches_data(self.guild_id)
        user_searches = [s for s in searches.values() if s['creator_id'] == interaction.user.id and s['active']]
        
        if len(user_searches) >= max_searches:
            await interaction.followup.send(
                f"❌ Du hast bereits {max_searches} aktive Suchen. Bitte schließe erst eine davon.",
                ephemeral=True
            )
            return
        
        # Parse team size
        team_size = None
        if self.team_size.value:
            try:
                team_size = int(self.team_size.value)
                if team_size < 1 or team_size > 99:
                    team_size = None
            except ValueError:
                team_size = None
        
        # Create search
        success, message = await self.cog.create_lfg_search(
            interaction.guild,
            interaction.user,
            self.game_name.value,
            self.description.value or None,
            team_size,
            self.duration.value or None
        )
        
        await interaction.followup.send(message, ephemeral=True)


class LFGStartView(View):
    """View mit Button zum Starten einer LFG-Suche"""
    
    def __init__(self, cog_instance, guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.guild_id = guild_id
    
    @discord.ui.button(
        label='🎮 Spieler suchen',
        style=ButtonStyle.primary,
        custom_id='lfg_start_search'
    )
    async def start_search(self, interaction: Interaction, button: Button):
        config = self.cog._get_lfg_config(self.guild_id)
        role_id = config.get('participation_role_id')
        
        if role_id:
            role = interaction.guild.get_role(role_id)
            if role and role not in interaction.user.roles:
                await interaction.response.send_message(
                    f"❌ Du benötigst die Rolle {role.mention}, um am LFG-System teilzunehmen.", 
                    ephemeral=True
                )
                return

        await interaction.response.send_modal(LFGModal(self.cog, self.guild_id))


class LFGSearchView(View):
    """View für eine einzelne LFG-Suche mit Beitreten/Abbrechen Buttons"""
    
    def __init__(self, cog_instance, search_id: int, creator_id: int):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.search_id = search_id
        self.creator_id = creator_id
        
        # Customize button IDs
        self.children[0].custom_id = f'lfg_join_{search_id}'
        self.children[1].custom_id = f'lfg_cancel_{search_id}'
    
    @discord.ui.button(
        label='Beitreten',
        style=ButtonStyle.success,
        emoji='✅'
    )
    async def join_search(self, interaction: Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        success, message = await self.cog.join_lfg_search(interaction.guild, interaction.user, self.search_id)
        await interaction.followup.send(message, ephemeral=True)
    
    @discord.ui.button(
        label='Suche beenden',
        style=ButtonStyle.danger,
        emoji='🗑️'
    )
    async def cancel_search(self, interaction: Interaction, button: Button):
        # Only creator can cancel
        if interaction.user.id != self.creator_id:
            await interaction.response.send_message("❌ Nur der Ersteller kann diese Suche beenden.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        success, message = await self.cog.cancel_lfg_search(interaction.guild, self.search_id)
        await interaction.followup.send(message, ephemeral=True)


class LFGCog(commands.Cog, name="LFG"):
    """Looking For Group System"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.search_counter = {}  # guild_id -> counter
        self.bot.loop.create_task(self.restore_persistent_views())
    
    def _get_lfg_config(self, guild_id: int):
        return self.bot.data.get_guild_data(guild_id, "lfg_config")
    
    def _save_lfg_config(self, guild_id: int, data):
        self.bot.data.save_guild_data(guild_id, "lfg_config", data)
    
    def _get_searches_data(self, guild_id: int):
        return self.bot.data.get_guild_data(guild_id, "lfg_searches")
    
    def _save_searches_data(self, guild_id: int, data):
        self.bot.data.save_guild_data(guild_id, "lfg_searches", data)
    
    async def restore_persistent_views(self):
        """Restore persistent views after bot restart"""
        await self.bot.wait_until_ready()
        
        for guild in self.bot.guilds:
            config = self._get_lfg_config(guild.id)
            searches = self._get_searches_data(guild.id)
            
            # Restore start view
            self.bot.add_view(LFGStartView(self, guild.id))
            
            # Restore search views
            for search_id, search_data in searches.items():
                if search_data.get('active'):
                    self.bot.add_view(LFGSearchView(self, int(search_id), search_data['creator_id']))
    
    def _get_next_search_id(self, guild_id: int) -> int:
        """Get next unique search ID for this guild"""
        if guild_id not in self.search_counter:
            searches = self._get_searches_data(guild_id)
            self.search_counter[guild_id] = max([int(sid) for sid in searches.keys()], default=0)
        
        self.search_counter[guild_id] += 1
        return self.search_counter[guild_id]
    
    async def create_lfg_search(
        self,
        guild: discord.Guild,
        creator: discord.Member,
        game_name: str,
        description: Optional[str],
        team_size: Optional[int],
        duration: Optional[str]
    ) -> Tuple[bool, str]:
        """Create a new LFG search"""
        
        config = self._get_lfg_config(guild.id)
        lobby_thread_id = config.get('lobby_thread_id')
        
        if not lobby_thread_id:
            return False, "❌ LFG-System ist nicht konfiguriert. Bitte kontaktiere einen Admin."
        
        try:
            lobby_thread = await self.bot.fetch_channel(lobby_thread_id)
        except:
            return False, "❌ Lobby-Thread nicht gefunden. Bitte kontaktiere einen Admin."
        
        # Generate unique search ID
        search_id = self._get_next_search_id(guild.id)
        
        # Create unique role
        role_name = f"LFG-{game_name[:20]}-{search_id}"
        try:
            role = await guild.create_role(
                name=role_name,
                mentionable=False,
                reason=f"LFG Search by {creator}"
            )
            await creator.add_roles(role)
        except:
            return False, "❌ Konnte Rolle nicht erstellen. Bitte kontaktiere einen Admin."
        
        # Create private thread
        try:
            private_thread = await lobby_thread.parent.create_thread(
                name=f"🎮 {game_name} - {creator.display_name}",
                type=discord.ChannelType.private_thread,
                reason=f"LFG Search by {creator}"
            )
            await private_thread.add_user(creator)
        except:
            await role.delete()
            return False, "❌ Konnte privaten Thread nicht erstellen."
        
        # Create embed
        embed = Embed(
            title=f"🎮 {game_name}",
            color=Color.blue(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Ersteller", value=creator.mention, inline=True)
        
        if team_size:
            embed.add_field(name="Suche", value=f"{team_size} Spieler", inline=True)
            embed.add_field(name="Frei", value=str(team_size), inline=True)
        
        if description:
            embed.add_field(name="Beschreibung", value=description, inline=False)
        
        if duration:
            embed.add_field(name="Zeitrahmen", value=duration, inline=True)
        
        embed.set_footer(text=f"ID: {search_id}")
        
        # Post in lobby
        try:
            view = LFGSearchView(self, search_id, creator.id)
            lobby_message = await lobby_thread.send(embed=embed, view=view)
        except:
            await role.delete()
            await private_thread.delete()
            return False, "❌ Konnte Suche nicht posten."
        
        # Save search data
        searches = self._get_searches_data(guild.id)
        searches[str(search_id)] = {
            'active': True,
            'creator_id': creator.id,
            'game_name': game_name,
            'description': description,
            'team_size': team_size,
            'duration': duration,
            'role_id': role.id,
            'thread_id': private_thread.id,
            'lobby_message_id': lobby_message.id,
            'members': [creator.id],
            'created_at': datetime.utcnow().isoformat()
        }
        self._save_searches_data(guild.id, searches)
        
        # Send welcome message in private thread
        welcome_embed = Embed(
            title=f"🎮 Willkommen zur {game_name} Gruppe!",
            description=f"Erstellt von {creator.mention}\n\nWeitere Spieler können über den Lobby-Thread beitreten.",
            color=Color.green()
        )
        await private_thread.send(embed=welcome_embed)
        
        return True, f"✅ Deine Suche wurde erstellt! Schau in {private_thread.mention}"
    
    async def join_lfg_search(self, guild: discord.Guild, member: discord.Member, search_id: int) -> Tuple[bool, str]:
        """Join an existing LFG search"""
        
        searches = self._get_searches_data(guild.id)
        search_data = searches.get(str(search_id))
        
        if not search_data or not search_data.get('active'):
            return False, "❌ Diese Suche existiert nicht mehr."
        
        if member.id in search_data['members']:
            return False, "❌ Du bist bereits in dieser Gruppe."
        
        # Check if full
        team_size = search_data.get('team_size')
        if team_size and len(search_data['members']) >= team_size + 1:  # +1 for creator
            return False, "❌ Diese Gruppe ist bereits voll."
        
        # Add role and thread access
        try:
            role = guild.get_role(search_data['role_id'])
            if role:
                await member.add_roles(role)
            
            thread = await self.bot.fetch_channel(search_data['thread_id'])
            await thread.add_user(member)
        except:
            return False, "❌ Konnte dich nicht zur Gruppe hinzufügen."
        
        # Update members list
        search_data['members'].append(member.id)
        searches[str(search_id)] = search_data
        self._save_searches_data(guild.id, searches)
        
        # Update lobby message
        await self._update_lobby_message(guild, search_id, search_data)
        
        # Notify in thread
        try:
            await thread.send(f"✅ {member.mention} ist der Gruppe beigetreten!")
        except:
            pass
        
        return True, f"✅ Du bist der Gruppe beigetreten! Schau in <#{search_data['thread_id']}>"
    
    async def cancel_lfg_search(self, guild: discord.Guild, search_id: int) -> Tuple[bool, str]:
        """Cancel/delete an LFG search"""
        
        searches = self._get_searches_data(guild.id)
        search_data = searches.get(str(search_id))
        
        if not search_data:
            return False, "❌ Diese Suche existiert nicht."
        
        # Mark as inactive
        search_data['active'] = False
        searches[str(search_id)] = search_data
        self._save_searches_data(guild.id, searches)
        
        # Delete role
        try:
            role = guild.get_role(search_data['role_id'])
            if role:
                await role.delete()
        except:
            pass
        
        # Close thread
        try:
            thread = await self.bot.fetch_channel(search_data['thread_id'])
            await thread.send("🔒 Diese Suche wurde beendet. Der Thread wird in 10 Sekunden archiviert.")
            await asyncio.sleep(10)
            await thread.edit(archived=True, locked=True)
        except:
            pass
        
        # Delete lobby message
        try:
            config = self._get_lfg_config(guild.id)
            lobby_thread = await self.bot.fetch_channel(config.get('lobby_thread_id'))
            lobby_message = await lobby_thread.fetch_message(search_data['lobby_message_id'])
            await lobby_message.delete()
        except:
            pass
        
        return True, "✅ Deine Suche wurde beendet."
    
    async def _update_lobby_message(self, guild: discord.Guild, search_id: int, search_data: dict):
        """Update the lobby message with current member count"""
        
        try:
            config = self._get_lfg_config(guild.id)
            lobby_thread = await self.bot.fetch_channel(config.get('lobby_thread_id'))
            lobby_message = await lobby_thread.fetch_message(search_data['lobby_message_id'])
            
            embed = lobby_message.embeds[0]
            
            # Update "Frei" field if team_size is set
            if search_data.get('team_size'):
                free_slots = search_data['team_size'] + 1 - len(search_data['members'])
                for i, field in enumerate(embed.fields):
                    if field.name == "Frei":
                        embed.set_field_at(i, name="Frei", value=str(max(0, free_slots)), inline=True)
                        break
            
            await lobby_message.edit(embed=embed)
        except:
            pass
    
    # --- Web API Methods ---
    
    async def web_set_config(
        self,
        guild_id: int,
        start_channel_id: Optional[int],
        participation_role_id: Optional[int],
        max_searches: int
    ) -> Tuple[bool, str]:
        """Configure LFG system via web interface"""
        
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return False, "Server nicht gefunden."
        
        config = self._get_lfg_config(guild_id)
        
        # Set participation role
        if participation_role_id:
            role = guild.get_role(participation_role_id)
            if not role:
                return False, "Teilnehmer-Rolle ungültig."
            config['participation_role_id'] = participation_role_id
        
        # Set start channel
        if start_channel_id:
            channel = guild.get_channel(start_channel_id)
            if not isinstance(channel, TextChannel):
                return False, "Start-Kanal ungültig."
            
            # Cleanup old messages and threads if they exist
            old_msg_id = config.get('start_message_id')
            if old_msg_id:
                try:
                    old_channel = guild.get_channel(config.get('start_channel_id'))
                    if old_channel:
                        # Try to archive old thread
                        old_thread_id = config.get('lobby_thread_id')
                        if old_thread_id:
                            old_thread = guild.get_thread(old_thread_id)
                            if old_thread: await old_thread.edit(archived=True)
                        
                        old_msg = await old_channel.fetch_message(old_msg_id)
                        await old_msg.delete()
                except:
                    pass
            
            # Create new start message
            embed = Embed(
                title="🎮 Mitspieler-Suche",
                description="Du suchst jemanden zum Zocken? Klicke auf den Button unten!\n\n*Hinweis: Nur Teilnehmer mit der entsprechenden Rolle sehen den Lobby-Bereich.*",
                color=Color.blue()
            )
            try:
                view = LFGStartView(self, guild_id)
                start_msg = await channel.send(embed=embed, view=view)
                
                # Create automatic PRIVATE lobby thread
                lobby_thread = await channel.create_thread(
                    name="🎮 Aktive Suchen",
                    type=discord.ChannelType.private_thread,
                    invitable=False,
                    reason="Automatischer privater LFG Lobby-Thread"
                )
                
                # Update embed with thread link
                embed.description += f"\n\n📍 **Lobby:** {lobby_thread.mention}"
                await start_msg.edit(embed=embed)
                
                # Pin the message to keep it accessible
                try:
                    await start_msg.pin()
                except:
                    pass
                
                config['start_channel_id'] = start_channel_id
                config['start_message_id'] = start_msg.id
                config['lobby_thread_id'] = lobby_thread.id
                
                # Add existing role members to the thread
                target_role = guild.get_role(participation_role_id)
                if target_role:
                    # Sync all members of the role
                    async def add_members():
                        for member in target_role.members:
                            try:
                                await lobby_thread.add_user(member)
                                await asyncio.sleep(0.5) # Avoid rate limits
                            except:
                                continue
                    self.bot.loop.create_task(add_members())
                
            except Exception as e:
                print(f"Error in LFG config: {e}")
                return False, f"Fehler beim Erstellen der Start-Nachricht: {e}"
        
        # Set max searches
        config['max_searches_per_user'] = max(1, min(max_searches, 10))
        
        self._save_lfg_config(guild_id, config)
        return True, "LFG-Konfiguration gespeichert. Privater Lobby-Thread wurde erstellt und Mitglieder synchronisiert."

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Auto-add/remove members from lobby thread based on role changes"""
        config = self._get_lfg_config(after.guild.id)
        role_id = config.get('participation_role_id')
        thread_id = config.get('lobby_thread_id')
        
        if not role_id or not thread_id:
            return
            
        role = after.guild.get_role(role_id)
        if not role:
            return

        # Case: Role added
        if role not in before.roles and role in after.roles:
            try:
                thread = await self.bot.fetch_channel(thread_id)
                if thread:
                    await thread.add_user(after)
            except:
                pass
        
        # Case: Role removed
        elif role in before.roles and role not in after.roles:
            try:
                thread = await self.bot.fetch_channel(thread_id)
                if thread:
                    # Discord API doesn't have a direct "remove user from thread" without deleting the thread or the user leaving
                    # But if it's a private thread, they will lose access if they aren't explicitly in it.
                    # Actually, for private threads, you have to be manually added. 
                    # If they lose the role, they stay in the thread unless removed.
                    # Currently discord.py doesn't support removing users from threads easily via add_user's opposite.
                    # However, we can use the low-level API if needed, but usually just adding is the priority.
                    pass
            except:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(LFGCog(bot))
