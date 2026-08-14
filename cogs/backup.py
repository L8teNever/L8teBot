import discord
from discord.ext import commands, tasks
import datetime
import os
import shutil
import asyncio
from zoneinfo import ZoneInfo
from typing import Optional
from utils.config import GUILDS_DATA_DIR, BASE_DIR

GERMAN_TZ = ZoneInfo("Europe/Berlin")
MAX_FILE_SIZE_MB = 8  # Discord free tier limit


class BackupCog(commands.Cog, name="Backup"):
    """Cog für automatische Server-Backups."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        """Wird aufgerufen, wenn das Cog geladen wird."""
        self.backup_check_loop.start()

    async def cog_unload(self):
        """Wird aufgerufen, wenn das Cog entladen wird."""
        self.backup_check_loop.cancel()

    # --- Data Access Methods ---

    def _get_backup_config(self, guild_id: int) -> dict:
        """Lädt die Backup-Konfiguration für einen Server."""
        return self.bot.data.get_guild_data(guild_id, "backup")

    def _save_backup_config(self, guild_id: int, data: dict):
        """Speichert die Backup-Konfiguration für einen Server."""
        self.bot.data.save_guild_data(guild_id, "backup", data)

    # --- Main Backup Loop ---

    @tasks.loop(minutes=1)
    async def backup_check_loop(self):
        """Prüft jede Minute, ob Backups ausgeführt werden müssen."""
        try:
            now = datetime.datetime.now(GERMAN_TZ)

            for guild in self.bot.guilds:
                try:
                    # Prüfe, ob Backup-Modul aktiviert ist
                    guild_config = self.bot.data.get_server_config(guild.id)
                    if "Backup" not in guild_config.get('enabled_cogs', []):
                        continue

                    backup_config = self._get_backup_config(guild.id)
                    if not backup_config.get('enabled'):
                        continue

                    # Prüfe, ob jetzt Backup durchgeführt werden sollte
                    if self._should_backup_now(backup_config, now):
                        await self._perform_backup(guild, backup_config)

                except Exception as e:
                    print(f"[Backup] Fehler bei Guild {guild.id}: {e}")

        except Exception as e:
            print(f"[Backup] Fehler in backup_check_loop: {e}")

    @backup_check_loop.before_loop
    async def before_backup_check_loop(self):
        """Warte bis der Bot ready ist."""
        await self.bot.wait_until_ready()

    # --- Time Checking Logic ---

    def _should_backup_now(self, config: dict, now: datetime.datetime) -> bool:
        """
        Prüft, ob ein Backup zu diesem Zeitpunkt durchgeführt werden sollte.

        Returns:
            True, wenn jetzt ein Backup laufen sollte
        """
        # Hole konfigurierte Zeit (z.B. "03:00")
        backup_time_str = config.get('backup_time', '03:00')
        try:
            hour, minute = map(int, backup_time_str.split(':'))
        except (ValueError, AttributeError):
            return False

        # Prüfe, ob aktuelle Zeit passt (innerhalb 1-Minuten Fenster)
        if now.hour != hour or now.minute != minute:
            return False

        # Prüfe Häufigkeit (Tage seit letztem Backup)
        last_backup_str = config.get('last_backup_timestamp')
        if not last_backup_str:
            return True  # Noch nie gebackupt

        try:
            last_backup = datetime.datetime.fromisoformat(last_backup_str)
            frequency_days = config.get('backup_frequency_days', 1)
            days_since_backup = (now - last_backup).days

            return days_since_backup >= frequency_days
        except (ValueError, TypeError):
            return True  # Invalides Format, führe Backup durch

    # --- Backup Execution ---

    async def _get_or_create_dashboard_backup_thread(self, guild: discord.Guild, config: dict) -> Optional[discord.Thread]:
        """
        Sucht oder erstellt einen dedizierten Backup-Post (Thread) im Moderator-Dashboard Forum.
        Speichert die Thread-ID in der Config für dauerhafte Persistenz auch nach Neustarts.
        """
        try:
            dash_config = self.bot.data.get_guild_data(guild.id, "dashboard_config")
            forum_channel_id = dash_config.get('forum_channel_id')

            if not forum_channel_id:
                dash_cog = self.bot.get_cog("Dashboard")
                if dash_cog and hasattr(dash_cog, 'setup_dashboard_forum'):
                    await dash_cog.setup_dashboard_forum(guild)
                    dash_config = self.bot.data.get_guild_data(guild.id, "dashboard_config")
                    forum_channel_id = dash_config.get('forum_channel_id')

            if not forum_channel_id:
                print(f"[Backup] Dashboard Forum Kanal nicht gefunden für Guild {guild.id}")
                return None

            forum_channel = guild.get_channel(forum_channel_id)
            if not forum_channel or not isinstance(forum_channel, discord.ForumChannel):
                try:
                    forum_channel = await self.bot.fetch_channel(forum_channel_id)
                except Exception:
                    return None

            if not isinstance(forum_channel, discord.ForumChannel):
                return None

            # Überprüfe, ob bereits eine bekannte Thread ID in den Configs existiert
            thread_id = config.get('dashboard_backup_thread_id')
            thread = None

            if thread_id:
                thread = forum_channel.get_thread(thread_id)
                if not thread:
                    try:
                        fetched = await self.bot.fetch_channel(thread_id)
                        if isinstance(fetched, discord.Thread):
                            thread = fetched
                    except Exception:
                        thread = None

            # Falls kein Thread existiert oder gelöscht wurde -> neuen Backup Post/Thread erstellen
            if not thread:
                embed_intro = discord.Embed(
                    title="💾 Server-Backup Archiv",
                    description=(
                        "In diesem Post/Thread werden alle automatischen und manuellen Server-Backups als ZIP-Dateien archiviert.\n\n"
                        "💡 *Dieser Post wird automatisch vom L8teBot Backup-Modul verwaltet und bleibt auch nach Neustarts erhalten.*"
                    ),
                    color=discord.Color.blue(),
                    timestamp=datetime.datetime.now(GERMAN_TZ)
                )
                embed_intro.set_footer(text="L8teBot Backup-System • Nur für Moderatoren")

                thread_with_msg = await forum_channel.create_thread(
                    name="💾 Server-Backups",
                    embed=embed_intro
                )
                thread = thread_with_msg.thread
                config['dashboard_backup_thread_id'] = thread.id
                self._save_backup_config(guild.id, config)

                try:
                    await thread.edit(pinned=True, reason="Backup Thread im Dashboard gepinnt")
                except Exception:
                    pass

            return thread
        except Exception as e:
            print(f"[Backup] Fehler in _get_or_create_dashboard_backup_thread: {e}")
            return None

    async def _perform_backup(self, guild: discord.Guild, config: dict):
        """
        Führt ein Backup für einen Server durch.

        1. Erstellt ZIP-Datei der Server-Daten
        2. Prüft Dateigröße
        3. Sendet ZIP zu Discord-Channel oder Dashboard-Forum-Post
        4. Aktualisiert last_backup_timestamp
        """
        try:
            use_dashboard = config.get('use_dashboard_forum', False) or (config.get('destination_type') == 'dashboard_forum')
            channel = None

            if use_dashboard:
                channel = await self._get_or_create_dashboard_backup_thread(guild, config)

            if not channel:
                channel_id = config.get('channel_id')
                if channel_id:
                    channel = guild.get_channel(channel_id)

            if not channel:
                print(f"[Backup] Ungültiges Backup-Ziel für Guild {guild.id}")
                return

            # Erstelle Backup-ZIP
            backup_file_path = await self._create_backup_zip(guild.id)

            if not backup_file_path:
                try:
                    await channel.send("❌ **Backup fehlgeschlagen**: Konnte ZIP-Datei nicht erstellen.")
                except (discord.Forbidden, AttributeError):
                    pass
                return

            # Dateigröße und Splitting
            try:
                file_size_bytes = os.path.getsize(backup_file_path)
            except OSError:
                if os.path.exists(backup_file_path):
                    os.remove(backup_file_path)
                return

            MAX_FILE_SIZE_BYTES = int(MAX_FILE_SIZE_MB * 1024 * 1024)
            parts = []
            
            if file_size_bytes > MAX_FILE_SIZE_BYTES:
                part_num = 1
                with open(backup_file_path, 'rb') as f:
                    while True:
                        chunk = f.read(MAX_FILE_SIZE_BYTES)
                        if not chunk:
                            break
                        part_file = f"{backup_file_path}.part{part_num}"
                        with open(part_file, 'wb') as p:
                            p.write(chunk)
                        parts.append(part_file)
                        part_num += 1
            else:
                parts = [backup_file_path]

            # Sende zu Discord
            timestamp = datetime.datetime.now(GERMAN_TZ).strftime('%d.%m.%Y %H:%M Uhr')
            filename_base = f"{guild.name}_Backup_{datetime.datetime.now(GERMAN_TZ).strftime('%Y%m%d_%H%M%S')}.zip"

            try:
                for i, part_path in enumerate(parts):
                    part_filename = filename_base if len(parts) == 1 else f"{filename_base}.part{i+1}"
                    
                    with open(part_path, 'rb') as f:
                        discord_file = discord.File(f, filename=part_filename)
                        
                        if len(parts) == 1:
                            title = "✅ Server-Backup erstellt"
                            desc = f"Automatisches Backup vom {timestamp}"
                        else:
                            title = f"✅ Server-Backup erstellt (Teil {i+1}/{len(parts)})"
                            desc = f"Teil {i+1} des automatischen Backups vom {timestamp}"
                            
                        embed = discord.Embed(
                            title=title,
                            description=desc,
                            color=discord.Color.green()
                        )
                        part_size_mb = os.path.getsize(part_path) / (1024 * 1024)
                        embed.add_field(name="Dateigröße", value=f"{part_size_mb:.2f} MB", inline=True)
                        embed.add_field(name="Server", value=f"{guild.name}", inline=True)
                        embed.set_footer(text=f"Guild ID: {guild.id}")

                        await channel.send(embed=embed, file=discord_file)
                        
            except discord.Forbidden:
                print(f"[Backup] Keine Berechtigung, in Ziel-Kanal/Thread {channel.id} zu schreiben")
            except discord.HTTPException as e:
                print(f"[Backup] HTTP-Fehler beim Upload: {e}")
            finally:
                # Cleanup: Lösche temp-Dateien
                if os.path.exists(backup_file_path):
                    try:
                        os.remove(backup_file_path)
                    except OSError:
                        pass
                for part_path in parts:
                    if part_path != backup_file_path and os.path.exists(part_path):
                        try:
                            os.remove(part_path)
                        except OSError:
                            pass

            # Aktualisiere last_backup_timestamp
            config['last_backup_timestamp'] = datetime.datetime.now(GERMAN_TZ).isoformat()
            self._save_backup_config(guild.id, config)

            print(f"[Backup] Successfully backed up guild {guild.id} ({guild.name})")

        except Exception as e:
            print(f"[Backup] Fehler beim Backup der Guild {guild.id}: {e}")

    # --- ZIP Creation ---

    async def _create_backup_zip(self, guild_id: int) -> Optional[str]:
        """
        Erstellt eine ZIP-Datei der Guild-Daten.

        Args:
            guild_id: Discord Guild ID

        Returns:
            Pfad zur ZIP-Datei oder None bei Fehler
        """
        try:
            guild_data_dir = os.path.join(GUILDS_DATA_DIR, str(guild_id))

            # Prüfe, ob Datenverzeichnis existiert
            if not os.path.exists(guild_data_dir):
                print(f"[Backup] Kein Datenverzeichnis für Guild {guild_id}")
                return None

            # Erstelle temp Verzeichnis für Backups
            temp_backup_dir = os.path.join(BASE_DIR, 'temp_backups')
            os.makedirs(temp_backup_dir, exist_ok=True)

            # Erstelle unique temp-Datei Pfad
            timestamp = datetime.datetime.now(GERMAN_TZ).strftime('%Y%m%d_%H%M%S_%f')
            zip_path = os.path.join(temp_backup_dir, f"backup_{guild_id}_{timestamp}")

            # Erstelle ZIP-Archiv (shutil.make_archive fügt .zip automatisch hinzu)
            shutil.make_archive(
                zip_path,                    # Basis-Name (ohne .zip)
                'zip',                       # Format
                root_dir=guild_data_dir,     # Verzeichnis zum Zipen
                base_dir='.'                 # Inhalt zipen, nicht den Ordner
            )

            return f"{zip_path}.zip"

        except Exception as e:
            print(f"[Backup] Fehler beim Erstellen der ZIP für Guild {guild_id}: {e}")
            return None

    # --- Discord Commands ---

    @commands.command(name="backup")
    @commands.has_permissions(administrator=True)
    async def manual_backup(self, ctx):
        """
        Manuelles Backup auslösen (nur Admin).

        Verwendung: !backup
        """
        guild_config = self.bot.data.get_server_config(ctx.guild.id)
        is_enabled = "Backup" in guild_config.get('enabled_cogs', [])

        if not is_enabled:
            await ctx.send(
                "❌ **Backup-Modul nicht aktiviert**\n"
                "Bitte aktiviere das Modul im Web-Dashboard unter den Server-Einstellungen."
            )
            return

        backup_config = self._get_backup_config(ctx.guild.id)

        if not backup_config.get('enabled'):
            await ctx.send(
                "❌ **Backups sind deaktiviert**\n"
                "Bitte aktiviere Backups im Web-Dashboard."
            )
            return

        use_dashboard = backup_config.get('use_dashboard_forum', False) or (backup_config.get('destination_type') == 'dashboard_forum')

        if not backup_config.get('channel_id') and not use_dashboard:
            await ctx.send(
                "❌ **Kein Backup-Ziel konfiguriert**\n"
                "Bitte wähle einen Backup-Kanal oder das Dashboard-Forum im Web-Dashboard aus."
            )
            return

        # Starte Backup
        await ctx.send("🔄 **Erstelle Backup...**")
        await self._perform_backup(ctx.guild, backup_config)
        await ctx.send("✅ **Backup abgeschlossen!** Prüfe den Backup-Kanal.")

    @manual_backup.error
    async def manual_backup_error(self, ctx, error):
        """Error-Handler für den Backup-Befehl."""
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ Du benötigst Administrator-Rechte, um diesen Befehl zu nutzen.")
        else:
            await ctx.send(f"❌ Fehler: {str(error)}")


async def setup(bot):
    """Registriert das BackupCog bei dem Bot."""
    await bot.add_cog(BackupCog(bot))
