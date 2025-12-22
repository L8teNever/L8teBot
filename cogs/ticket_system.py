import discord
from discord.ext import commands
from discord import app_commands, Embed, Color, TextStyle, Interaction, ButtonStyle, TextChannel, CategoryChannel, Role
import io
import logging
from datetime import datetime
from typing import Optional
import json
import os
import random
import string

logger = logging.getLogger('TicketSystemCog')

# --- UI-Komponenten (Views & Modals) ---

class TicketDetailModal(discord.ui.Modal):
    def __init__(self, ticket_reason: dict, view_instance: discord.ui.View):
        super().__init__(title=f"Ticket für: {ticket_reason.get('name', 'Unbekannt')}")
        self.ticket_reason = ticket_reason
        self.view_instance = view_instance
        
        self.problem_description = discord.ui.TextInput(
            label="Bitte beschreibe dein Anliegen",
            style=TextStyle.long,
            placeholder="Je mehr Details, desto besser können wir helfen.",
            required=True,
            max_length=1024
        )
        self.add_item(self.problem_description)

    async def on_submit(self, interaction: Interaction):
        # Ticket erstellen
        await self.view_instance.cog.create_ticket_channel(interaction, self.ticket_reason, self.problem_description.value)

        # Panel-Nachricht im Ticket-Channel zurücksetzen (Dropdown wieder anzeigen)
        guild = interaction.guild
        config = self.view_instance.cog._get_ticket_config(guild.id)
        ticket_channel_id = config.get('ticket_channel')
        if ticket_channel_id:
            channel = guild.get_channel(ticket_channel_id)
            if channel:
                old_msg_id = config.get('ticket_message_id')
                if old_msg_id:
                    try:
                        old_msg = await channel.fetch_message(old_msg_id)
                        embed = discord.Embed(
                            title="Support-Tickets",
                            description="Um ein Ticket zu erstellen, wähle bitte einen passenden Grund aus dem Menü unten aus.",
                            color=discord.Color.blurple()
                        )
                        view = TicketCreationView(self.view_instance.cog, guild.id)
                        await old_msg.edit(embed=embed, view=view)
                        return  # <--- Nach erfolgreichem Bearbeiten abbrechen!
                    except Exception:
                        pass  # Wenn Bearbeiten fehlschlägt, neue Nachricht senden

        # Nur wenn keine alte Nachricht bearbeitet werden konnte:
        embed = discord.Embed(
            title="Support-Tickets",
            description="Um ein Ticket zu erstellen, wähle bitte einen passenden Grund aus dem Menü unten aus.",
            color=discord.Color.blurple()
        )
        view = TicketCreationView(self.view_instance.cog, guild.id)
        try:
            new_msg = await channel.send(embed=embed, view=view)
            config['ticket_message_id'] = new_msg.id
            self.view_instance.cog._save_ticket_config(guild.id, config)
        except Exception:
            pass

class TicketReasonSelect(discord.ui.Select):
    def __init__(self, cog_instance: commands.Cog, guild_id: int):
        self.cog = cog_instance
        config = self.cog._get_ticket_config(guild_id)
        ticket_reasons = config.get('ticket_reasons', [])

        options = [
            discord.SelectOption(
                label=reason['name'],
                description=reason.get('description', ''),
                value=reason['name'],
                emoji=reason.get('emoji') or None
            )
            for reason in ticket_reasons
        ]
        if not options:
            options.append(discord.SelectOption(label="Keine Gründe konfiguriert", value="no_options", emoji="❌"))

        super().__init__(
            placeholder="Wähle einen Grund für dein Ticket...", 
            min_values=1, 
            max_values=1, 
            options=options,
            custom_id=f"ticket_reason_select:{guild_id}"
        )

    async def callback(self, interaction: Interaction):
        if self.values[0] == "no_options":
            await interaction.response.send_message("Derzeit sind keine Ticket-Gründe konfiguriert.", ephemeral=True)
            return

        selected_reason_name = self.values[0]
        config = self.cog._get_ticket_config(interaction.guild.id)
        ticket_reasons = config.get('ticket_reasons', [])
        
        reason_details = next((r for r in ticket_reasons if r['name'] == selected_reason_name), None)

        if reason_details:
            modal = TicketDetailModal(reason_details, self.view)
            await interaction.response.send_modal(modal)
        else:
            await interaction.response.send_message("Dieser Ticket-Grund scheint nicht mehr zu existieren.", ephemeral=True)

class TicketCreationView(discord.ui.View):
    def __init__(self, cog_instance: commands.Cog, guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.add_item(TicketReasonSelect(cog_instance, guild_id))

class TicketClaimView(discord.ui.View):
    def __init__(self, cog_instance: commands.Cog, ticket_id: int):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.ticket_id = ticket_id
        self.children[0].custom_id = f"claim_ticket_{ticket_id}"

    @discord.ui.button(label="Ticket beanspruchen", style=ButtonStyle.success)
    async def claim_ticket(self, interaction: Interaction, button: discord.ui.Button):
        await self.cog.claim_ticket_logic(interaction, self.ticket_id, button)

class TicketControlPanelView(discord.ui.View):
    def __init__(self, cog_instance: commands.Cog, ticket_id: int):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.ticket_id = ticket_id
        self.children[0].custom_id = f"close_ticket_{ticket_id}"
        self.children[1].custom_id = f"add_user_{ticket_id}"

    @discord.ui.button(
        label="Ticket schließen",
        style=ButtonStyle.danger,
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        guild = interaction.guild
        if user.guild_permissions.administrator:
            await self.cog.close_ticket_logic(interaction, self.ticket_id)
        else:
            await interaction.response.send_modal(CloseTicketReasonModal(self.cog, self.ticket_id))

    @discord.ui.button(
        label="User hinzufügen",
        style=ButtonStyle.primary,
    )
    async def add_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddUserToTicketModal(self.cog, self.ticket_id))

class TicketSystemCog(commands.Cog, name="Ticket-System"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.loop.create_task(self.restore_persistent_views())

    # --- Data Helpers ---
    def _get_ticket_config(self, guild_id: int):
        return self.bot.data.get_guild_data(guild_id, "ticket_config")

    def _save_ticket_config(self, guild_id: int, data):
        self.bot.data.save_guild_data(guild_id, "ticket_config", data)

    def _get_tickets_data(self, guild_id: int):
        return self.bot.data.get_guild_data(guild_id, "tickets")

    def _save_tickets_data(self, guild_id: int, data):
        self.bot.data.save_guild_data(guild_id, "tickets", data)

    async def restore_persistent_views(self):
        await self.bot.wait_until_ready()
        
        for guild in self.bot.guilds:
            config = self._get_ticket_config(guild.id)
            if 'ticket_channel' in config:
                self.bot.add_view(TicketCreationView(self, guild.id))

            tickets = self._get_tickets_data(guild.id)
            for ticket_id_str, ticket_data in tickets.items():
                if ticket_data.get('status') == 'offen':
                    ticket_id = int(ticket_id_str)
                    if ticket_data.get('initial_message_id'):
                        self.bot.add_view(TicketClaimView(self, ticket_id))
                    if ticket_data.get('control_panel_message_id'):
                        self.bot.add_view(TicketControlPanelView(self, ticket_id))

    async def log_action(self, guild: discord.Guild, embed: Embed):
        config = self._get_ticket_config(guild.id)
        log_channel_id = config.get('log_channel')
        if log_channel_id:
            log_channel = guild.get_channel(log_channel_id)
            if isinstance(log_channel, TextChannel):
                try:
                    await log_channel.send(embed=embed)
                except discord.Forbidden:
                    logger.warning(f"Keine Berechtigung im Log-Kanal {log_channel_id} auf Server {guild.id}.")
                except Exception as e:
                    logger.error(f"Fehler beim Senden der Log-Nachricht: {e}")

    async def create_ticket_channel(self, interaction: Interaction, reason: dict, description: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        user = interaction.user
        
        config = self._get_ticket_config(guild.id)
        tickets = self._get_tickets_data(guild.id)

        # --- LIMIT PRÜFEN ---
        max_tickets_per_user = config.get('max_tickets_per_user', 1)
        user_open_tickets = 0
        for t in tickets.values():
            if t.get('ersteller_id') == user.id and t.get('status') == 'offen':
                user_open_tickets += 1
        if user_open_tickets >= max_tickets_per_user:
            await interaction.followup.send(
                f"Du hast bereits das Maximum von {max_tickets_per_user} offenen Tickets.", ephemeral=True
            )
            return

        category_id = config.get('ticket_kategorie')
        if not category_id:
            await interaction.followup.send("Die Ticket-Kategorie wurde noch nicht eingerichtet.", ephemeral=True)
            return

        category = guild.get_channel(category_id)
        if not isinstance(category, discord.CategoryChannel):
            await interaction.followup.send("Die konfigurierte Ticket-Kategorie konnte nicht gefunden werden.", ephemeral=True)
            return
            
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True, embed_links=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        # Kombiniere allgemeine und grund-spezifische Support-Rollen
        general_support_roles = config.get('support_roles', [])
        reason_specific_roles = reason.get('roles', [])
        final_role_ids = set(general_support_roles + reason_specific_roles)

        for role_id in final_role_ids:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=False)
        
        try:
            channel_name = f"ticket-{user.name}-{reason['name']}".lower().replace(" ", "-")
            ticket_channel = await category.create_text_channel(name=channel_name, overwrites=overwrites)
        except discord.Forbidden:
            await interaction.followup.send("Ich habe keine Berechtigung, Kanäle zu erstellen.", ephemeral=True)
            return
        except Exception as e:
            logger.error(f"Fehler beim Erstellen des Ticket-Kanals: {e}")
            await interaction.followup.send("Ein Fehler ist beim Erstellen des Kanals aufgetreten.", ephemeral=True)
            return

        # --- Ticket-ID generieren ---
        ticket_custom_id = generate_ticket_id()

        await interaction.followup.send(f"Dein Ticket wurde erstellt! -> {ticket_channel.mention}", ephemeral=True)

        ticket_embed = Embed(
            title=f"Ticket: {reason['name']}",
            description=f"**Erstellt von:** {user.mention}\n**Grund:** {reason['name']}\n\n**Anliegen:**\n{description}\n\n**Ticket-ID:** `{ticket_custom_id}`",
            color=Color.blue(),
            timestamp=datetime.utcnow()
        )
        ticket_embed.set_footer(text=f"Ticket-ID: {ticket_channel.id}")

        role_mentions = " ".join([f"<@&{role_id}>" for role_id in final_role_ids if guild.get_role(role_id)])
        initial_message_content = f"Willkommen {user.mention}! Ein Teammitglied wird sich bald kümmern. {role_mentions}"

        # HIER: Button für den Ersteller einbauen
        user_close_view = TicketUserCloseView(self, ticket_channel.id, user.id)
        await ticket_channel.send(content=initial_message_content, embed=ticket_embed, view=user_close_view)

        # --- NEU: Privaten Thread für Admin/Support erstellen ---
        thread = await ticket_channel.create_thread(
            name="⛔｜Konsole",
            type=discord.ChannelType.private_thread,
            invitable=False
        )
        # Nur Supporter/Admins zum Thread hinzufügen (NICHT den Ersteller!)
        try:
            for role_id in final_role_ids:
                role = guild.get_role(role_id)
                if role:
                    for member in role.members:
                        await thread.add_user(member)
        except Exception:
            pass  # Fehler beim Hinzufügen ignorieren

        # Control Panel und Claim-Button in den Thread posten
        claim_view = TicketClaimView(self, ticket_channel.id)
        claim_embed = Embed(title="Ticket Unbeansprucht", description="Ein Supporter kann dieses Ticket beanspruchen.", color=Color.orange())
        initial_msg = await thread.send(embed=claim_embed, view=claim_view)

        control_panel_view = TicketControlPanelView(self, ticket_channel.id)
        panel_embed = Embed(title="Admin Control Panel", description="Aktionen für dieses Ticket.", color=Color.dark_grey())
        control_panel_msg = await thread.send(embed=panel_embed, view=control_panel_view)

        ticket_data = {
            "ticket_id": ticket_channel.id,
            "custom_ticket_id": ticket_custom_id,
            "server_id": guild.id,
            "ersteller_id": user.id,
            "bearbeiter_id": None,
            "status": "offen",
            "reason": reason['name'],
            "initial_message_id": initial_msg.id,
            "control_panel_message_id": control_panel_msg.id,
            "admin_thread_id": thread.id
        }
        
        tickets[str(ticket_channel.id)] = ticket_data
        self._save_tickets_data(guild.id, tickets)
        
        log_embed = Embed(title="Neues Ticket erstellt", color=Color.green())
        log_embed.add_field(name="Ersteller", value=user.mention, inline=True).add_field(name="Kanal", value=ticket_channel.mention, inline=True).add_field(name="Grund", value=reason['name'], inline=True).add_field(name="Anliegen", value=description, inline=False)
        await self.log_action(guild, log_embed)

        # --- USER PER DM BENACHRICHTIGEN ---
        try:
            dm_embed = Embed(
                title="Ihr Ticket wurde erstellt!",
                description=(
                    f"**Server:** {guild.name}\n"
                    f"**Ticket-ID:** `{ticket_custom_id}`\n"
                    f"**Grund:** {reason['name']}\n"
                    f"**Beschreibung:** {description}\n\n"
                    "Ein Admin oder Supporter wird sich bald um Ihr Anliegen kümmern."
                ),
                color=Color.green()
            )
            await user.send(embed=dm_embed)
        except Exception:
            pass  # DM konnte nicht gesendet werden

    async def claim_ticket_logic(self, interaction: Interaction, ticket_id: int, button: discord.ui.Button):
        await interaction.response.defer()
        guild = interaction.guild
        user = interaction.user
        ticket_id_str = str(ticket_id)

        config = self._get_ticket_config(guild.id)
        tickets = self._get_tickets_data(guild.id)
        ticket_data = tickets.get(ticket_id_str)

        # Berechtigungsprüfung: Allgemeine UND spezifische Rollen
        general_support_roles = set(config.get('support_roles', []))
        
        all_reasons = config.get('ticket_reasons', [])
        ticket_reason_name = ticket_data.get('reason')
        reason_details = next((r for r in all_reasons if r.get('name') == ticket_reason_name), None)
        
        reason_roles = set(reason_details.get('roles', [])) if reason_details else set()
        
        allowed_role_ids = general_support_roles.union(reason_roles)
        user_role_ids = {role.id for role in user.roles}

        if not allowed_role_ids.intersection(user_role_ids) and not user.guild_permissions.administrator:
            await interaction.followup.send("Du hast nicht die erforderliche Rolle, um dieses Ticket zu beanspruchen.", ephemeral=True)
            return
        
        if ticket_data and ticket_data['bearbeiter_id'] is None:
            ticket_data['bearbeiter_id'] = user.id
            self._save_tickets_data(guild.id, tickets)

            ticket_channel = guild.get_channel(ticket_id)
            if isinstance(ticket_channel, TextChannel):
                await ticket_channel.set_permissions(user, send_messages=True)

            # --- Admin-Thread umbenennen ---
            admin_thread_id = ticket_data.get("admin_thread_id")
            admin_thread = None
            if admin_thread_id:
                admin_thread = guild.get_channel(admin_thread_id)
                # Fallback: Versuche Thread direkt zu holen, falls nicht im Cache
                if not admin_thread:
                    try:
                        admin_thread = await guild.fetch_channel(admin_thread_id)
                    except Exception as e:
                        logger.warning(f"Thread konnte nicht geladen werden: {e}")
                if admin_thread:
                    try:
                        await admin_thread.edit(name=f"✅｜{user.display_name}")
                    except Exception as e:
                        logger.warning(f"Thread konnte nicht umbenannt werden: {e}")

            claimed_embed = Embed(title="Ticket beansprucht", description=f"Dieses Ticket wird von {user.mention} bearbeitet.", color=Color.green())
            button.disabled = True
            button.label = "Beansprucht"
            await interaction.message.edit(embed=claimed_embed, view=button.view)

            log_embed = Embed(title="Ticket beansprucht", description=f"{user.mention} hat das Ticket {ticket_channel.mention} beansprucht.", color=Color.blue())
            await self.log_action(guild, log_embed)

            # --- USER PER DM BENACHRICHTIGEN ---
            ersteller_id = ticket_data.get("ersteller_id")
            custom_ticket_id = ticket_data.get("custom_ticket_id")
            if ersteller_id:
                ersteller = guild.get_member(ersteller_id)
                if ersteller:
                    try:
                        dm_embed = Embed(
                            title="Ihr Ticket wird jetzt bearbeitet",
                            description=(
                                f"Ein Admin oder Supporter ({user.display_name}) hat Ihr Ticket übernommen.\n"
                                f"**Ticket-ID:** `{custom_ticket_id}`"
                            ),
                            color=Color.blue()
                        )
                        await ersteller.send(embed=dm_embed)
                    except Exception:
                        pass  # DM konnte nicht gesendet werden
        else:
            await interaction.followup.send("Dieses Ticket wurde bereits beansprucht oder existiert nicht mehr.", ephemeral=True)

    async def close_ticket_logic(self, interaction: Interaction, ticket_id: int):
        await interaction.response.send_message("Schließe Ticket...", ephemeral=True)
        ticket_channel = interaction.guild.get_channel(ticket_id)
        if isinstance(ticket_channel, TextChannel):
            transcript_file = await self.create_transcript(ticket_channel)
            log_embed = Embed(title="Ticket geschlossen", description=f"Ticket {ticket_channel.name} (`{ticket_id}`) wurde von {interaction.user.mention} geschlossen.", color=Color.red())
            await self.log_action(interaction.guild, log_embed)
            
            config = self._get_ticket_config(interaction.guild.id)
            if 'log_channel' in config:
                log_channel = interaction.guild.get_channel(config['log_channel'])
                if isinstance(log_channel, TextChannel):
                    await log_channel.send(file=transcript_file)
            
            # --- USER PER DM BENACHRICHTIGEN ---
            tickets = self._get_tickets_data(interaction.guild.id)
            ticket_data = tickets.get(str(ticket_id))
            if ticket_data:
                ersteller_id = ticket_data.get("ersteller_id")
                custom_ticket_id = ticket_data.get("custom_ticket_id")
                if ersteller_id:
                    ersteller = interaction.guild.get_member(ersteller_id)
                    if ersteller:
                        try:
                            dm_embed = Embed(
                                title="Dein Ticket wurde geschlossen",
                                description=(
                                    f"Dein Ticket (`{custom_ticket_id}`) wurde soeben geschlossen.\n"
                                    "Wir hoffen, wir konnten dir gut helfen!\n"
                                    "Solltest du weitere Fragen haben, kannst du jederzeit ein neues Ticket eröffnen."
                                ),
                                color=Color.red()
                            )
                            await ersteller.send(embed=dm_embed)
                        except Exception:
                            pass  # DM konnte nicht gesendet werden

            await ticket_channel.delete(reason="Ticket geschlossen.")
            
            # --- WRAPPED INTEGRATION ---
            if ticket_data:
                bearbeiter_id = ticket_data.get('bearbeiter_id')
                if bearbeiter_id:
                    wrapped_cog = self.bot.get_cog("Wrapped")
                    if wrapped_cog:
                         # Synchroner Aufruf, da Methode nicht async ist (Datenbank-Sim via JSON)
                         wrapped_cog.register_ticket_processed(interaction.guild.id, bearbeiter_id)

            if str(ticket_id) in tickets:
                del tickets[str(ticket_id)]
                self._save_tickets_data(interaction.guild.id, tickets)

    async def create_transcript(self, channel: TextChannel) -> Optional[discord.File]:
        try:
            messages = []
            async for message in channel.history(limit=None, oldest_first=True):
                messages.append(f"[{message.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {message.author.name}: {message.content}")
            transcript_content = "\n".join(messages)
            return discord.File(io.BytesIO(transcript_content.encode('utf-8')), filename=f"transcript-{channel.name}.txt")
        except Exception as e:
            logger.error(f"Fehler bei der Transkripterstellung für Kanal {channel.id}: {e}")
            return None

    async def update_ticket_creation_panel(self, guild):
        config = self._get_ticket_config(guild.id)
        ticket_channel_id = config.get('ticket_channel')
        if not ticket_channel_id:
            return

        channel = guild.get_channel(ticket_channel_id)
        if not channel:
            return

        embed = discord.Embed(
            title="Support-Tickets",
            description="Um ein Ticket zu erstellen, wähle bitte einen passenden Grund aus dem Menü unten aus.",
            color=discord.Color.blurple()
        )
        view = TicketCreationView(self, guild.id)

        old_msg_id = config.get('ticket_message_id')
        if old_msg_id:
            try:
                old_msg = await channel.fetch_message(old_msg_id)
                await old_msg.edit(embed=embed, view=view)
                return  # Nur bearbeiten, keine neue Nachricht senden!
            except Exception:
                pass  # Nachricht existiert nicht mehr oder Fehler beim Bearbeiten

        # Falls keine alte Nachricht existiert, sende eine neue und speichere die ID
        new_msg = await channel.send(embed=embed, view=view)
        config['ticket_message_id'] = new_msg.id
        self._save_ticket_config(guild.id, config)

    # --- Web API Methoden ---
    async def web_set_config(self, guild_id: int, ticket_channel_id: Optional[int], ticket_kategorie_id: Optional[int], log_channel_id: Optional[int], max_tickets_per_user: int) -> tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return False, "Server nicht gefunden."

        config = self._get_ticket_config(guild_id)

        config['ticket_channel'] = ticket_channel_id
        config['ticket_kategorie'] = ticket_kategorie_id
        config['log_channel'] = log_channel_id
        config['max_tickets_per_user'] = max_tickets_per_user

        self._save_ticket_config(guild_id, config)
        
        # Panel-Update anstoßen
        await self.update_ticket_creation_panel(guild)

        return True, "Ticket-Konfiguration gespeichert und Panel aktualisiert!"

    async def web_add_support_role(self, guild_id: int, role_id: int) -> tuple[bool, str]:
        config = self._get_ticket_config(guild_id)
        support_roles = config.setdefault('support_roles', [])
        if not isinstance(support_roles, list):
            support_roles = config['support_roles'] = [support_roles]
        
        if role_id not in support_roles:
            support_roles.append(role_id)
            self._save_ticket_config(guild_id, config)
            return True, "Support-Rolle hinzugefügt."
        else:
            return False, "Diese Rolle ist bereits als Support-Rolle hinzugefügt."

    async def web_remove_support_role(self, guild_id: int, role_id: int) -> tuple[bool, str]:
        config = self._get_ticket_config(guild_id)
        support_roles = config.setdefault('support_roles', [])

        if role_id in support_roles:
            support_roles.remove(role_id)
            self._save_ticket_config(guild_id, config)
            return True, "Support-Rolle entfernt."
        else:
            return False, "Diese Rolle ist nicht als Support-Rolle hinzugefügt."

    async def web_add_reason(self, guild_id: int, name: str, desc: str, emoji: str = None) -> tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return False, "Server nicht gefunden."

        config = self._get_ticket_config(guild_id)
        reasons = config.setdefault('ticket_reasons', [])
        
        if name and not any(r['name'] == name for r in reasons):
            reasons.append({'name': name, 'description': desc, 'emoji': emoji or '', 'roles': []})
            self._save_ticket_config(guild_id, config)
            await self.update_ticket_creation_panel(guild)
            return True, f"Grund '{name}' hinzugefügt."
        else:
            return False, f"Grund '{name}' existiert bereits oder ist ungültig."

    async def web_remove_reason(self, guild_id: int, name: str) -> tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return False, "Server nicht gefunden."

        config = self._get_ticket_config(guild_id)
        reasons = config.setdefault('ticket_reasons', [])
        
        original_len = len(reasons)
        config['ticket_reasons'] = [r for r in reasons if r.get('name') != name]
        
        if len(config['ticket_reasons']) < original_len:
            self._save_ticket_config(guild_id, config)
            await self.update_ticket_creation_panel(guild)
            return True, f"Grund '{name}' entfernt."
        else:
            return False, f"Grund '{name}' nicht gefunden."

    async def web_add_reason_role(self, guild_id: int, reason_name: str, role_id: int) -> tuple[bool, str]:
        config = self._get_ticket_config(guild_id)
        reasons = config.setdefault('ticket_reasons', [])
        
        for r in reasons:
            if r.get('name') == reason_name:
                reason_roles = r.setdefault('roles', [])
                if role_id not in reason_roles:
                    reason_roles.append(role_id)
                    self._save_ticket_config(guild_id, config)
                    return True, f"Rolle zum Grund '{reason_name}' hinzugefügt."
                else:
                    return False, f"Diese Rolle ist bereits dem Grund '{reason_name}' zugewiesen."
        return False, f"Grund '{reason_name}' nicht gefunden."

    async def web_remove_reason_role(self, guild_id: int, reason_name: str, role_id: int) -> tuple[bool, str]:
        config = self._get_ticket_config(guild_id)
        reasons = config.setdefault('ticket_reasons', [])

        for r in reasons:
            if r.get('name') == reason_name:
                if role_id in r.get('roles', []):
                    r['roles'].remove(role_id)
                    self._save_ticket_config(guild_id, config)
                    return True, f"Rolle vom Grund '{reason_name}' entfernt."
                else:
                    return False, "Rolle nicht bei diesem Grund gefunden."
        return False, f"Grund '{reason_name}' nicht gefunden."

def generate_ticket_id():
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=4)) + '-' + ''.join(random.choices(chars, k=4))

class TicketCloseConfirmView(discord.ui.View):
    def __init__(self, cog, ticket_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.ticket_id = ticket_id

    @discord.ui.button(label="Ticket endgültig schließen", style=discord.ButtonStyle.danger)
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        guild_id = str(interaction.guild.id)
        ticket_id = str(self.ticket_id)
        pending = getattr(self.cog.bot, "pending_ticket_closures", {})
        closure = pending.get((guild_id, ticket_id))
        # Prüfe ob Supporter/Admin
        if not (user.guild_permissions.administrator or user.guild_permissions.manage_channels):
            await interaction.response.send_message("Nur ein Supporter/Admin kann das Ticket endgültig schließen.", ephemeral=True)
            return
        # Ticket schließen
        await self.cog.close_ticket_logic(interaction, self.ticket_id)
        # Optional: Info-Message mit Grund
        channel = interaction.guild.get_channel(self.ticket_id)
        if channel and closure:
            await channel.send(f"Das Ticket wurde von {user.mention} geschlossen.\n**Grund des Users:** {closure['reason']}")
            del pending[(guild_id, ticket_id)]
        try:
            await interaction.response.send_message("Ticket wurde geschlossen.", ephemeral=True)
        except: pass

class CloseTicketReasonModal(discord.ui.Modal):
    def __init__(self, cog, ticket_id):
        super().__init__(title="Ticket schließen – Grund angeben")
        self.cog = cog
        self.ticket_id = ticket_id
        self.reason = discord.ui.TextInput(
            label="Warum möchtest du das Ticket schließen?",
            style=discord.TextStyle.long,
            required=True,
            max_length=512
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        ticket_id = str(self.ticket_id)
        if not hasattr(self.cog.bot, "pending_ticket_closures"):
            self.cog.bot.pending_ticket_closures = {}
        self.cog.bot.pending_ticket_closures[(guild_id, ticket_id)] = {
            "user_id": interaction.user.id,
            "reason": self.reason.value
        }
        # Admin-Thread holen
        tickets = self.cog._get_tickets_data(interaction.guild.id)
        admin_thread_id = None
        ticket_data = tickets.get(ticket_id)
        if ticket_data:
            admin_thread_id = ticket_data.get("admin_thread_id")
        admin_thread = None
        if admin_thread_id:
            try:
                admin_thread = await interaction.guild.fetch_channel(admin_thread_id)
            except Exception as e:
                logger.warning(f"Admin-Thread konnte nicht geladen werden: {e}")

        embed = discord.Embed(
            title="Ticket-Schließanfrage",
            description=(
                f"{interaction.user.mention} möchte dieses Ticket schließen.\n\n"
                f"**Grund:**\n{self.reason.value}\n\n"
                f"Ein Supporter/Admin kann das Ticket jetzt endgültig schließen."
            ),
            color=discord.Color.orange()
        )

        if admin_thread:
            await admin_thread.send(
                embed=embed,
                view=TicketCloseConfirmView(self.cog, self.ticket_id)
            )
        else:
            await interaction.response.send_message(
                "Fehler: Der Admin-Thread konnte nicht gefunden werden. Bitte wende dich an einen Admin.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Dein Schließwunsch wurde eingereicht und muss von einem Supporter/Admin bestätigt werden.",
            ephemeral=True
        )

class TicketUserCloseView(discord.ui.View):
    def __init__(self, cog, ticket_id, ersteller_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.ticket_id = ticket_id
        self.ersteller_id = ersteller_id

    @discord.ui.button(label="Ticket schließen", style=discord.ButtonStyle.danger, custom_id="user_close_ticket")
    async def user_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Nur der Ersteller darf den Button nutzen
        if interaction.user.id != self.ersteller_id:
            await interaction.response.send_message(
                "Nur der Ersteller dieses Tickets kann diesen Button benutzen.", ephemeral=True
            )
            return
        # Modal für Schließgrund anzeigen
        try:
            await interaction.response.send_modal(CloseTicketReasonModal(self.cog, self.ticket_id))
        except Exception as e:
            print(f"Fehler beim Öffnen des Modals: {e}")
            await interaction.response.send_message("Fehler beim Öffnen des Modals.", ephemeral=True)

class AddUserToTicketModal(discord.ui.Modal):
    def __init__(self, cog, ticket_id):
        super().__init__(title="User zu Ticket hinzufügen")
        self.cog = cog
        self.ticket_id = ticket_id
        self.user_input = discord.ui.TextInput(
            label="User-ID oder @Username",
            placeholder="z.B. 123456789012345678 oder @Benutzer",
            required=True,
            max_length=64
        )
        self.add_item(self.user_input)

    async def on_submit(self, interaction: discord.Interaction):
        value = self.user_input.value.strip()
        guild = interaction.guild
        ticket_channel = guild.get_channel(self.ticket_id)
        member = None

        # Versuche User zu bekommen (ID oder Mention)
        if value.isdigit():
            member = guild.get_member(int(value))
        elif value.startswith("<@") and value.endswith(">"):
            user_id = value.replace("<@", "").replace("!", "").replace(">", "")
            if user_id.isdigit():
                member = guild.get_member(int(user_id))
        else:
            # Versuche per Namen
            member = discord.utils.get(guild.members, name=value) or discord.utils.get(guild.members, display_name=value)

        if not member:
            await interaction.response.send_message("User nicht gefunden. Bitte gib eine gültige User-ID oder einen korrekten Namen an.", ephemeral=True)
            return

        if isinstance(ticket_channel, TextChannel):
            try:
                await ticket_channel.set_permissions(member, read_messages=True, send_messages=True, attach_files=True, embed_links=True)
                await interaction.response.send_message(f"{member.mention} wurde zum Ticket hinzugefügt.", ephemeral=True)
                await ticket_channel.send(f"{member.mention} wurde von {interaction.user.mention} zum Ticket hinzugefügt.")
            except Exception:
                await interaction.response.send_message("Fehler beim Hinzufügen des Users.", ephemeral=True)
        else:
            await interaction.response.send_message("Ticket-Kanal nicht gefunden.", ephemeral=True)

class TicketControlPanelView(discord.ui.View):
    def __init__(self, cog_instance: commands.Cog, ticket_id: int):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.ticket_id = ticket_id
        # Setze custom_id für die Buttons nachträglich
        self.children[0].custom_id = f"close_ticket_{ticket_id}"
        self.children[1].custom_id = f"add_user_{ticket_id}"

    @discord.ui.button(
        label="Ticket schließen",
        style=ButtonStyle.danger,
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        guild = interaction.guild
        if user.guild_permissions.administrator:
            await self.cog.close_ticket_logic(interaction, self.ticket_id)
        else:
            await interaction.response.send_modal(CloseTicketReasonModal(self.cog, self.ticket_id))

    @discord.ui.button(
        label="User hinzufügen",
        style=ButtonStyle.primary,
    )
    async def add_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddUserToTicketModal(self.cog, self.ticket_id))

async def setup(bot: commands.Bot):
    await bot.add_cog(TicketSystemCog(bot))