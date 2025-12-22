import discord
from discord.ext import commands
from discord import ui
import asyncio

# --- UI Elemente (Modals, Dropdowns und Views) ---

def create_control_embed(channel: discord.VoiceChannel, owner: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title="Kanal-Steuerung",
        description=f"Verwalte hier deinen temporären Kanal.",
        color=discord.Color.blue()
    )
    embed.add_field(name="👑 Kanal-Inhaber", value=owner.mention if owner else "Niemand", inline=False)
    limit = channel.user_limit if channel.user_limit > 0 else "Unbegrenzt"
    embed.add_field(name="👥 Benutzerlimit", value=str(limit), inline=True)
    locked = not channel.permissions_for(channel.guild.default_role).connect
    embed.add_field(name="🔒 Status", value="Gesperrt" if locked else "Offen", inline=True)
    embed.set_footer(text=f"Kanal-ID: {channel.id}")
    return embed

class RenameChannelModal(ui.Modal, title="Kanal umbenennen"):
    def __init__(self, channel: discord.VoiceChannel, view_instance):
        super().__init__()
        self.channel = channel
        self.view_instance = view_instance
        self.name_input = ui.TextInput(label="Neuer Kanalname", default=channel.name, max_length=100)
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        await self.channel.edit(name=self.name_input.value, reason=f"Geändert von {interaction.user}")
        embed = create_control_embed(self.channel, self.view_instance.get_owner(interaction.guild))
        await interaction.response.edit_message(embed=embed)

class SetLimitModal(ui.Modal, title="Benutzerlimit setzen"):
    def __init__(self, channel: discord.VoiceChannel, view_instance):
        super().__init__()
        self.channel = channel
        self.view_instance = view_instance
        self.limit_input = ui.TextInput(label="Max. Benutzer (0-99)", default=str(channel.user_limit), max_length=2)
        self.add_item(self.limit_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit = int(self.limit_input.value)
            if not 0 <= limit <= 99: raise ValueError
        except ValueError:
            return await interaction.response.send_message("Bitte eine Zahl zwischen 0-99 eingeben.", ephemeral=True)

        await self.channel.edit(user_limit=limit, reason=f"Geändert von {interaction.user}")
        embed = create_control_embed(self.channel, self.view_instance.get_owner(interaction.guild))
        await interaction.response.edit_message(embed=embed)

class TransferOwnerSelect(ui.Select):
    def __init__(self, cog, members: list[discord.Member]):
        self.cog = cog
        options = [discord.SelectOption(label=member.display_name, value=str(member.id)) for member in members]
        super().__init__(placeholder="Wähle den neuen Inhaber...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        new_owner_id = int(self.values[0])
        new_owner = interaction.guild.get_member(new_owner_id)
        channel = interaction.channel

        if not new_owner:
            return await interaction.response.send_message("Benutzer nicht gefunden.", ephemeral=True)

        # Set new owner permissions
        await channel.set_permissions(new_owner, overwrite=self.cog.get_owner_overwrites())
        # Reset old owner permissions
        await channel.set_permissions(interaction.user, overwrite=None)
        
        await self.cog.set_owner_for_channel(channel, new_owner)

        embed = create_control_embed(channel, new_owner)
        await interaction.response.edit_message(content=f"👑 Inhaberschaft an {new_owner.mention} übertragen!", embed=embed, view=None)

class ManageUserSelect(ui.Select):
    def __init__(self, channel: discord.VoiceChannel, action: str):
        self.channel = channel
        self.action = action
        
        if action == "add":
            placeholder = "Wähle Benutzer zum Einladen..."
            current_members_ids = {m.id for m in channel.members}
            overwritten_user_ids = {target.id for target in channel.overwrites if isinstance(target, discord.Member)}
            eligible_users = [
                m for m in channel.guild.members 
                if not m.bot and m.id not in current_members_ids and m.id not in overwritten_user_ids
            ]
        else: # remove
            placeholder = "Wähle Benutzer zum Entfernen..."
            eligible_users = [
                target for target, overwrite in channel.overwrites.items() 
                if isinstance(target, discord.Member) and (overwrite.connect or overwrite.view_channel)
            ]

        options = [discord.SelectOption(label=user.display_name, value=str(user.id)) for user in eligible_users[:25]]
        if not options:
            options = [discord.SelectOption(label="Keine Benutzer verfügbar", value="none")]
            
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options, disabled=len(options)==0 or options[0].value=="none")

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none": return
        member_id = int(self.values[0])
        member = interaction.guild.get_member(member_id)
        if not member:
            return await interaction.response.send_message("Benutzer nicht gefunden.", ephemeral=True)

        if self.action == "add":
            await self.channel.set_permissions(member, connect=True, view_channel=True, reason=f"Eingeladen von {interaction.user}")
            await interaction.response.send_message(f"{member.mention} wurde eingeladen und kann jetzt beitreten.", ephemeral=True)
        else: # remove
            await self.channel.set_permissions(member, overwrite=None, reason=f"Einladung entfernt von {interaction.user}")
            await interaction.response.send_message(f"Die Einladung für {member.mention} wurde entfernt.", ephemeral=True)
        
        await interaction.edit_original_response(view=None)


class ControlPanelView(ui.View):
    def __init__(self, temp_channel_cog):
        super().__init__(timeout=None)
        self.cog = temp_channel_cog
        self._update_dynamic_buttons()

    def _update_dynamic_buttons(self):
        # Remove existing dynamic buttons first
        for item in self.children[:]:
            if item.custom_id in ["temp_manage_users_add", "temp_manage_users_remove"]:
                self.remove_item(item)
        
        # This check needs a valid channel, will be called within an interaction
        channel = self.message.channel if hasattr(self, 'message') else None
        if channel:
            is_locked = not channel.permissions_for(channel.guild.default_role).connect
            is_hidden = not channel.permissions_for(channel.guild.default_role).view_channel
            
            if is_locked or is_hidden:
                self.add_item(self.create_manage_user_button("add"))
                self.add_item(self.create_manage_user_button("remove"))

    def create_manage_user_button(self, action: str):
        label = "Benutzer Einladen" if action == "add" else "Einladung Entfernen"
        emoji = "➕" if action == "add" else "➖"
        custom_id = f"temp_manage_users_{action}"
        button = ui.Button(label=label, style=discord.ButtonStyle.success, emoji=emoji, custom_id=custom_id)
        
        async def button_callback(interaction: discord.Interaction):
            view = ui.View(timeout=180)
            view.add_item(ManageUserSelect(interaction.channel, action))
            await interaction.response.send_message("Wähle einen Benutzer:", view=view, ephemeral=True)
        
        button.callback = button_callback
        return button
        
    def get_owner(self, guild: discord.Guild) -> discord.Member | None:
        owner_id = self.cog.get_owner_id_for_channel(guild.id, self.message.channel.id)
        return guild.get_member(owner_id) if owner_id else None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.data.get("custom_id", "").startswith("temp_manage_users"):
            owner_id = self.cog.get_owner_id_for_channel(interaction.guild.id, interaction.channel.id)
            if interaction.user.id == owner_id:
                return True
        
        owner_id = self.cog.get_owner_id_for_channel(interaction.guild.id, interaction.channel.id)
        if not owner_id or interaction.user.id != owner_id:
            await interaction.response.send_message("Nur der Kanal-Inhaber darf diese Buttons benutzen.", ephemeral=True)
            return False
        return True

    @ui.button(label="Umbenennen", style=discord.ButtonStyle.secondary, emoji="📝", custom_id="temp_rename", row=0)
    async def rename(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(RenameChannelModal(interaction.channel, self))

    @ui.button(label="Limit", style=discord.ButtonStyle.secondary, emoji="👥", custom_id="temp_limit", row=0)
    async def limit(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(SetLimitModal(interaction.channel, self))

    @ui.button(label="Sperren/Entsperren", style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="temp_lock", row=1)
    async def lock(self, interaction: discord.Interaction, button: ui.Button):
        channel = interaction.channel
        perms = channel.permissions_for(interaction.guild.default_role)
        await channel.set_permissions(interaction.guild.default_role, connect=not perms.connect)
        self._update_dynamic_buttons()
        await interaction.response.edit_message(embed=create_control_embed(channel, self.get_owner(interaction.guild)), view=self)

    @ui.button(label="Verstecken/Zeigen", style=discord.ButtonStyle.secondary, emoji="👁️", custom_id="temp_hide", row=1)
    async def hide(self, interaction: discord.Interaction, button: ui.Button):
        channel = interaction.channel
        perms = channel.permissions_for(interaction.guild.default_role)
        await channel.set_permissions(interaction.guild.default_role, view_channel=not perms.view_channel)
        self._update_dynamic_buttons()
        await interaction.response.edit_message(view=self)
        
    @ui.button(label="Inhaber übertragen", style=discord.ButtonStyle.primary, emoji="👑", custom_id="temp_transfer", row=2)
    async def transfer(self, interaction: discord.Interaction, button: ui.Button):
        other_members = [m for m in interaction.channel.members if not m.bot and m.id != interaction.user.id]
        if not other_members:
            return await interaction.response.send_message("Niemand anderes ist im Kanal, um die Inhaberschaft zu übernehmen.", ephemeral=True)
        
        view = ui.View(timeout=180)
        view.add_item(TransferOwnerSelect(self.cog, other_members))
        await interaction.response.send_message("Wähle den neuen Inhaber:", view=view, ephemeral=True)

    @ui.button(label="Löschen", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="temp_delete", row=2)
    async def delete(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        await self.cog.delete_channel(interaction.channel)


# --- Haupt-Cog Klasse ---

class TempChannel(commands.Cog, name="Temp-Channel"):
    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.add_persistent_views())

    async def add_persistent_views(self):
        await self.bot.wait_until_ready()
        self.bot.add_view(ControlPanelView(self))
        
    def get_owner_overwrites(self):
        return discord.PermissionOverwrite(
            manage_channels=True, move_members=True, mute_members=True, 
            deafen_members=True, manage_permissions=True
        )

    def get_guild_data(self, guild_id: int):
        data = self.bot.data.get_guild_data(guild_id, "temp_channel")
        data.setdefault('config', {})
        data.setdefault('active_channels', {})
        return data

    def save_guild_data(self, guild_id: int, data: dict):
        self.bot.data.save_guild_data(guild_id, "temp_channel", data)

    def get_owner_id_for_channel(self, guild_id: int, channel_id: int) -> int | None:
        guild_data = self.get_guild_data(guild_id)
        owner_id_str = guild_data['active_channels'].get(str(channel_id))
        return int(owner_id_str) if owner_id_str else None

    async def set_owner_for_channel(self, channel: discord.VoiceChannel, owner: discord.Member):
        guild_data = self.get_guild_data(channel.guild.id)
        guild_data['active_channels'][str(channel.id)] = str(owner.id)
        self.save_guild_data(channel.guild.id, guild_data)

    async def delete_channel(self, channel: discord.VoiceChannel):
        guild_data = self.get_guild_data(channel.guild.id)
        if str(channel.id) in guild_data['active_channels']:
            del guild_data['active_channels'][str(channel.id)]
            self.save_guild_data(channel.guild.id, guild_data)
        try:
            await channel.delete(reason="Temporärer Kanal nicht mehr benötigt")
        except (discord.NotFound, discord.Forbidden): pass

    @commands.Cog.listener()
    async def on_ready(self):
        print("Temp-Channel Cog: Überprüfe persistente Kanäle...")
        await asyncio.sleep(5)
        
        for guild in self.bot.guilds:
            guild_data = self.get_guild_data(guild.id)
            active_channels = guild_data.get('active_channels', {}).copy()
            for channel_id_str in active_channels:
                try:
                    channel = guild.get_channel(int(channel_id_str))
                    if not channel or (isinstance(channel, discord.VoiceChannel) and len(channel.members) == 0):
                        await self.delete_channel(channel)
                except Exception:
                    # Clean up invalid data if fetching channel fails hard (e.g. invalid ID)
                    del guild_data['active_channels'][channel_id_str]
                    self.save_guild_data(guild.id, guild_data)

        print("Temp-Channel Cog: Überprüfung abgeschlossen.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot: return
        guild_data = self.get_guild_data(member.guild.id)
        config = guild_data.get('config', {})
        trigger_channel_id = config.get('trigger_channel_id')
        active_channels = guild_data.get('active_channels', {})

        # --- KANAL VERLASSEN ---
        if before.channel and str(before.channel.id) in active_channels:
            channel = before.channel
            owner_id = self.get_owner_id_for_channel(member.guild.id, channel.id)
            if len(channel.members) == 0:
                await asyncio.sleep(3)
                if len(channel.members) == 0:
                    await self.delete_channel(channel)
                    return
            elif member.id == owner_id:
                potential_new_owners = sorted([m for m in channel.members if not m.bot], key=lambda m: m.joined_at)
                if potential_new_owners:
                    new_owner = potential_new_owners[0]
                    await channel.set_permissions(member, overwrite=None)
                    await channel.set_permissions(new_owner, overwrite=self.get_owner_overwrites())
                    await self.set_owner_for_channel(channel, new_owner)
                    async for msg in channel.history(limit=10):
                        if msg.author == self.bot.user and msg.embeds:
                            await msg.edit(embed=create_control_embed(channel, new_owner))
                            break

        # --- KANAL ERSTELLEN ---
        if after.channel and trigger_channel_id and after.channel.id == trigger_channel_id:
            if any(str(owner_id) == str(member.id) for owner_id in active_channels.values()): return
            name_format = config.get("channel_name_format", "🔊 {user}'s Raum")
            channel_name = name_format.format(user=member.display_name)
            try:
                new_channel = await member.guild.create_voice_channel(
                    name=channel_name, category=after.channel.category,
                    overwrites={member: self.get_owner_overwrites()},
                    reason=f"Temporärer Kanal für {member}"
                )
                await member.move_to(new_channel)
                await self.set_owner_for_channel(new_channel, member)
                view = ControlPanelView(self)
                embed = create_control_embed(new_channel, member)
                # Need to update view with dynamic buttons after it's attached to a message
                message = await new_channel.send(embed=embed, view=view)
                view.message = message 
                view._update_dynamic_buttons()
                await message.edit(view=view)
            except Exception as e:
                print(f"Fehler beim Erstellen von Temp-Channel: {e}")

async def setup(bot):
    await bot.add_cog(TempChannel(bot))