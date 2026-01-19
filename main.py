import discord
from discord.ext import commands, tasks
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from markupsafe import Markup
import datetime
from flask_discord import DiscordOAuth2Session, requires_authorization, Unauthorized
import random
from flask_cors import CORS
import json
import os
import sys
import asyncio
import threading
import subprocess
from werkzeug.middleware.proxy_fix import ProxyFix
import ssl
import urllib3

# Fix SSL issues on Windows
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# Create a more lenient SSL context for OAuth2
ssl._create_default_https_context = ssl._create_unverified_context

# --- UTILS IMPORT ---
from utils.config import *
import setup_server

# --- CONFIG CHECK & SETUP ---
if not os.path.exists(BOT_CONFIG_FILE):
    print("-------------------------------------------------")
    print("Config file not found. Starting Web Setup Wizard...")
    print("Please go to: http://localhost:5000")
    print("-------------------------------------------------")
    setup_server.run_setup_server()

# Verify content
try:
    with open(BOT_CONFIG_FILE, 'r') as f:
        c = json.load(f)
        if not c.get('token') or not c.get('DISCORD_CLIENT_ID'):
            print("Config incomplete. Starting Setup Wizard...")
            setup_server.run_setup_server()
except Exception:
    print("Config invalid. Starting Setup Wizard...")
    setup_server.run_setup_server()


from utils.data_manager import DataManager

# --- BOT-SETUP ---
# Initialisiere DataManager
data_manager = DataManager()
config = data_manager.load_global_config(BOT_CONFIG_FILE)

def get_prefix(bot, message):
    if not message.guild: return commands.when_mentioned_or('!')(bot, message)
    guild_config = bot.data.get_server_config(message.guild.id)
    return commands.when_mentioned_or(guild_config.get('prefix', '!'))(bot, message)

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None)

# Binde DataManager an den Bot
bot.config = config
bot.data = data_manager

# Überprüfe kritische Konfiguration für das Web-Dashboard
required_web_keys = ["DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET", "DISCORD_REDIRECT_URI"]
missing_web_keys = [key for key in required_web_keys if not config.get(key)]
if missing_web_keys:
    print(f"WARNUNG: Fehlende Konfiguration für das Web-Dashboard in config.json: {', '.join(missing_web_keys)}")
    print("Das Dashboard wird nicht funktionieren, bis diese Werte gesetzt sind.")

# --- WEB-SERVER (FLASK) SETUP ---
app = Flask(__name__, template_folder='web/templates', static_folder='web/static')
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = config.get("SECRET_KEY", "dev_secret_key_123456789")

# <-- HIER CORS HINZUFÜGEN:
CORS(app, resources={r"/bot_status": {"origins": "*"}}) 

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "true"
app.config["DISCORD_CLIENT_ID"] = config.get("DISCORD_CLIENT_ID")
app.config["DISCORD_CLIENT_SECRET"] = config.get("DISCORD_CLIENT_SECRET")
app.config["DISCORD_REDIRECT_URI"] = config.get("DISCORD_REDIRECT_URI")
app.config["DISCORD_BOT_TOKEN"] = config.get("token")

# Session Config - Using default Flask sessions (signed cookies)
app.config["SESSION_PERMANENT"] = True
app.config["SESSION_COOKIE_SECURE"] = False  # False for HTTP (localhost)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"  # Lax for better compatibility
app.config["PERMANENT_SESSION_LIFETIME"] = datetime.timedelta(days=7)
app.config["SESSION_COOKIE_NAME"] = "l8tebot_session"
app.config["SESSION_COOKIE_PATH"] = "/"

# Load version
VERSION = "Unknown"
try:
    with open(os.path.join(BASE_DIR, "version.txt"), "r") as f:
        VERSION = f.read().strip()
except:
    pass

# Make version available in all templates
@app.context_processor
def inject_version():
    return dict(bot_version=VERSION)

print(f"DEBUG: Redirect URI configured is: {app.config['DISCORD_REDIRECT_URI']}")
print("DEBUG: Make sure you access the dashboard via the SAME host/IP as in the Redirect URI!")
print(f"DEBUG: Secret key length: {len(app.secret_key)} characters")

# Ändere die Initialisierung, damit es keine Namenskollision gibt
discord_session = DiscordOAuth2Session(app)

@app.context_processor
def inject_user_and_auth():
    user = None
    if discord_session.authorized:
        try: user = discord_session.fetch_user()
        except Exception: pass
    return dict(user=user, discord_auth=discord_session)

# --- MAINTENANCE & DATA ROUTES ---
import shutil
import zipfile
from utils.migrate import process_migration_data

@app.route('/admin/maintenance')
@requires_authorization
def admin_maintenance():
    if not discord_session.authorized: return redirect(url_for('login'))
    user_id = discord_session.fetch_user().id
    # Prüfe, ob der User ein Bot-Owner ist (optional, hier prüfen wir erstmal ob er Admin auf IRGENDEINEM Server ist, oder man macht eine harte ID-Prüfung)
    # Für L8teBot nehmen wir an, wer Zugriff aufs Dashboard hat (Admins), darf evtl. seine eigenen Serverdaten nicht komplett kaputt machen.
    # ABER: Backup/Restore ist global für den Bot -> Das sollte NUR der BOt-Betreiber dürfen.
    # Da wir keine "Bot Owner" Rolle im Web haben, prüfen wir hier einfachheitshalber nichts weiter oder eine feste ID.
    # TODO: Besser absichern!
    
    return render_template('maintenance.html', admin_guilds=get_admin_guilds())

@app.route('/admin/backup/download')
@requires_authorization
def download_backup():
    # 1. Erstelle Zip von data/ folder INHALT (nicht den Ordner selbst)
    data_dir = os.path.join(os.getcwd(), DATA_DIR_NAME)
    if not os.path.exists(data_dir):
        flash("Data-Verzeichnis existiert nicht!", "danger")
        return redirect(url_for('admin_maintenance'))

    # Zip erstellen - packe den INHALT von data/, nicht data/ selbst
    backup_path = 'backup_data'
    shutil.make_archive(backup_path, 'zip', root_dir=data_dir, base_dir='.')
    
    # Datei senden
    return send_file(f'{backup_path}.zip', as_attachment=True, download_name=f"L8teBot_Backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")

@app.route('/admin/backup/upload', methods=['POST'])
@requires_authorization
def upload_backup():
    if 'backup_file' not in request.files:
        flash('Keine Datei ausgewählt', 'danger')
        return redirect(url_for('admin_maintenance'))
    
    file = request.files['backup_file']
    if file.filename == '':
        flash('Keine Datei ausgewählt', 'danger')
        return redirect(url_for('admin_maintenance'))

    if file and file.filename.endswith('.zip'):
        # Speichern und entpacken
        zip_path = os.path.join(os.getcwd(), 'uploaded_backup.zip')
        file.save(zip_path)
        
        data_dir = os.path.join(os.getcwd(), DATA_DIR_NAME)
        temp_extract_dir = os.path.join(os.getcwd(), 'temp_backup_extract')
        
        try:
            print(f"[BACKUP RESTORE] Starting restore process...")
            print(f"[BACKUP RESTORE] Data directory: {data_dir}")
            
            # Erstelle temporäres Verzeichnis
            os.makedirs(temp_extract_dir, exist_ok=True)
            
            # Entpacke in temporäres Verzeichnis
            print(f"[BACKUP RESTORE] Extracting backup...")
            shutil.unpack_archive(zip_path, temp_extract_dir)
            
            # Prüfe ob ein 'data' Unterordner existiert (vom Backup-Tool)
            extracted_data_dir = os.path.join(temp_extract_dir, 'data')
            if os.path.exists(extracted_data_dir):
                # Backup enthält 'data/' Ordner - kopiere Inhalt
                source_dir = extracted_data_dir
                print(f"[BACKUP RESTORE] Backup contains 'data' folder")
            else:
                # Backup ist direkt der Inhalt - nutze temp Verzeichnis
                source_dir = temp_extract_dir
                print(f"[BACKUP RESTORE] Backup is direct content")
            
            # Lösche alten Inhalt (außer config.json zur Sicherheit)
            print(f"[BACKUP RESTORE] Removing old data...")
            for item in os.listdir(data_dir):
                if item == 'config.json':
                    print(f"[BACKUP RESTORE] Keeping config.json")
                    continue
                item_path = os.path.join(data_dir, item)
                try:
                    if os.path.isdir(item_path):
                        print(f"[BACKUP RESTORE] Removing directory: {item}")
                        shutil.rmtree(item_path)
                    else:
                        print(f"[BACKUP RESTORE] Removing file: {item}")
                        os.remove(item_path)
                except Exception as e:
                    print(f"[BACKUP RESTORE] Error removing {item}: {e}")
            
            # Kopiere neue Daten
            print(f"[BACKUP RESTORE] Copying new data from {source_dir}...")
            items_copied = 0
            for item in os.listdir(source_dir):
                s = os.path.join(source_dir, item)
                d = os.path.join(data_dir, item)
                try:
                    if os.path.isdir(s):
                        print(f"[BACKUP RESTORE] Copying directory: {item}")
                        if os.path.exists(d):
                            shutil.rmtree(d)
                        shutil.copytree(s, d)
                    else:
                        if item == 'config.json':
                            print(f"[BACKUP RESTORE] Skipping config.json from backup")
                            continue
                        print(f"[BACKUP RESTORE] Copying file: {item}")
                        shutil.copy2(s, d)
                    items_copied += 1
                except Exception as e:
                    print(f"[BACKUP RESTORE] Error copying {item}: {e}")
            
            print(f"[BACKUP RESTORE] Copied {items_copied} items")
            
            # Force filesystem sync
            print(f"[BACKUP RESTORE] Syncing filesystem...")
            try:
                if hasattr(os, 'sync'):
                    os.sync()
            except:
                pass
            
            flash(f'Backup erfolgreich wiederhergestellt! ({items_copied} Elemente kopiert) Der Bot wird neu gestartet...', 'success')
            
            # Trigger restart nach kurzer Verzögerung
            def restart_bot():
                time.sleep(3)  # Längere Wartezeit für Filesystem-Sync
                print("[BACKUP RESTORE] Restarting bot...")
                os._exit(0)
            threading.Thread(target=restart_bot).start()
            
        except Exception as e:
            print(f"[BACKUP RESTORE] ERROR: {e}")
            import traceback
            traceback.print_exc()
            flash(f'Fehler beim Entpacken: {e}', 'danger')
        finally:
            # Aufräumen
            print(f"[BACKUP RESTORE] Cleaning up...")
            if os.path.exists(zip_path):
                os.remove(zip_path)
            if os.path.exists(temp_extract_dir):
                shutil.rmtree(temp_extract_dir)
    else:
        flash('Bitte eine .zip Datei hochladen', 'danger')

    return redirect(url_for('admin_maintenance'))

@app.route('/admin/import_legacy', methods=['POST'])
@requires_authorization
def import_legacy_data():
    if 'legacy_file' not in request.files:
        flash('Keine Datei ausgewählt', 'danger')
        return redirect(url_for('admin_maintenance'))
    
    file = request.files['legacy_file']
    module_name = request.form.get('module_name')
    
    if file.filename == '' or not module_name:
        flash('Datei oder Modul-Typ fehlt', 'danger')
        return redirect(url_for('admin_maintenance'))

    if file:
        try:
            content = json.load(file)
            count = process_migration_data(module_name, content, save_callback=bot.data.save_guild_data)
            flash(f'Import erfolgreich! {count} Einträge verarbeitet für Modul {module_name}.', 'success')
        except Exception as e:
            flash(f'Fehler beim Import: {e}', 'danger')

    return redirect(url_for('admin_maintenance'))


MANAGEABLE_COGS = ["Geburtstage", "Zählen", "Level-System", "Moderation", "Twitch", "Twitch-Live-Alert", "Ticket-System", "Temp-Channel", "Twitch-Clips", "Streak", "Gatekeeper", "Guard", "Global-Ban", "Wrapped", "LFG", "Mitspieler-Suche"]

# (Existing get_admin_guilds and check_guild_permissions are slightly below)

# (Existing get_admin_guilds and check_guild_permissions are slightly below)

def get_admin_guilds():
    if not discord_session.authorized: return []
    try:
        user_guilds = discord_session.fetch_guilds()
        return sorted([g for g in user_guilds if g.permissions.administrator and bot.get_guild(g.id)], key=lambda g: g.name)
    except Exception:
        return []

def check_guild_permissions(guild_id):
    try:
        user_guilds = discord_session.fetch_guilds()
        guild = next((g for g in user_guilds if g.id == guild_id), None)
        if not guild or not guild.permissions.administrator: return False
        if not bot.get_guild(guild_id): return False
        return True
    except Exception:
        return False

# --- AUTH & GENERAL ROUTES ---
@app.route("/")
def index():
    if discord_session.authorized:
        return redirect(url_for('dashboard'))
    return render_template("login.html")

@app.route("/login", strict_slashes=False)
def login():
    from flask import session
    import time
    
    # Rate limiting: Prevent multiple rapid login attempts
    last_login_time = session.get('_last_login_attempt', 0)
    current_time = time.time()
    
    if current_time - last_login_time < 5:  # 5 seconds cooldown
        print(f"DEBUG LOGIN: Rate limited - too soon after last attempt ({current_time - last_login_time:.1f}s ago)")
        flash("Bitte warte einen Moment bevor du dich erneut einloggst.", "warning")
        return redirect(url_for("index"))
    
    # Clear the entire session to start fresh
    session.clear()
    
    # Set session as permanent
    session.permanent = True
    session.modified = True
    session['_last_login_attempt'] = current_time
    
    # Debug: Print session info
    print(f"DEBUG LOGIN: Session cleared and reinitialized")
    print(f"DEBUG LOGIN: Session keys after clear: {list(session.keys())}")
    
    # Create OAuth session - this will set the state in the session
    response = discord_session.create_session(scope=['identify', 'guilds'])
    
    # Debug: Check if state was set
    print(f"DEBUG LOGIN: Session keys after create_session: {list(session.keys())}")
    if 'DISCORD_OAUTH2_STATE' in session:
        print(f"DEBUG LOGIN: OAuth state successfully set in session")
    else:
        print(f"DEBUG LOGIN: WARNING - OAuth state NOT in session!")
    
    return response

@app.route("/logout", strict_slashes=False)
def logout():
    discord_session.revoke()
    return redirect(url_for("index"))

@app.route("/callback", strict_slashes=False)
def callback():
    from flask import session
    import time
    
    # Debug: Print session and request info
    print(f"DEBUG CALLBACK: Session ID: {session.get('_id', 'NO_ID')}")
    print(f"DEBUG CALLBACK: Session keys: {list(session.keys())}")
    print(f"DEBUG CALLBACK: Request args: {dict(request.args)}")
    
    try:
        session.permanent = True
        session.modified = True
        discord_session.callback()
        print("DEBUG CALLBACK: OAuth callback successful!")
        return redirect(url_for("dashboard"))
    except Exception as e:
        error_str = str(e)
        print(f"Fehler während des OAuth2-Callbacks: {e}")
        
        # Spezifische Fehlerbehandlung
        if "invalid_client" in error_str:
            print("HINWEIS: 'invalid_client' bedeutet meistens, dass die Client ID oder das Client Secret in config.json falsch ist.")
            flash("OAuth2-Fehler: Ungültige Client-Konfiguration. Bitte kontaktiere den Bot-Administrator.", "danger")
        elif "mismatching_state" in error_str or "CSRF" in error_str:
            print("HINWEIS: CSRF State Mismatch - Dies kann durch Session-Probleme oder mehrfache Login-Versuche verursacht werden.")
            print(f"DEBUG: Session data at error: {dict(session)}")
            flash("Login fehlgeschlagen: Sitzungsfehler. Bitte versuche es erneut.", "warning")
            # Clear session and retry
            session.clear()
            return redirect(url_for("login"))
        elif "SSLError" in error_str or "SSL" in error_str:
            print("HINWEIS: SSL-Verbindungsfehler zu Discord. Dies kann ein temporäres Netzwerkproblem sein.")
            flash("Verbindungsfehler zu Discord. Bitte versuche es in einigen Sekunden erneut.", "warning")
            # Retry once after a short delay
            time.sleep(1)
            try:
                discord_session.callback()
                return redirect(url_for("dashboard"))
            except Exception as retry_error:
                print(f"Wiederholungsversuch fehlgeschlagen: {retry_error}")
                flash("Login fehlgeschlagen. Bitte versuche es später erneut.", "danger")
        else:
            flash(f"Login fehlgeschlagen: {error_str}", "danger")
        
        return redirect(url_for("index"))

@app.errorhandler(Unauthorized)
def redirect_unauthorized(e):
    return redirect(url_for("login"))

@app.route("/bot_status")
def bot_status():
    """
    Ein einfacher Endpunkt, der den Status des Bots meldet,
    einschließlich der Anzahl der moderierten Benutzer und Server.
    """
    total_users = sum(guild.member_count for guild in bot.guilds)
    total_guilds = len(bot.guilds)
    
    return jsonify(status="online", total_users=total_users, total_guilds=total_guilds)

# --- PROTECTED ROUTES ---
@app.route('/dashboard/')
@requires_authorization
def dashboard():
    return render_template('dashboard.html', guilds=get_admin_guilds())

@app.route('/guild/<int:guild_id>', methods=['GET', 'POST'])
@requires_authorization
def guild_settings(guild_id):
    if not check_guild_permissions(guild_id):
        flash("Du hast keine Berechtigung für diesen Server.", "danger")
        return redirect(url_for('dashboard'))
    
    guild = bot.get_guild(guild_id)
    if request.method == 'POST':
        # Laden der aktuellen Konfiguration
        guild_config = bot.data.get_server_config(guild_id)
        guild_config['prefix'] = request.form['prefix']
        welcome_channel_id = request.form.get('welcome_channel')
        guild_config['welcome_channel_id'] = int(welcome_channel_id) if welcome_channel_id else None
        
        # Speichern der Konfiguration
        bot.data.save_server_config(guild_id, guild_config)
        flash('Allgemeine Einstellungen gespeichert!', 'success')
        return redirect(url_for('guild_settings', guild_id=guild_id))

    guild_data = bot.data.get_server_config(guild_id)
    return render_template('guild.html', guild=guild, settings=guild_data, admin_guilds=get_admin_guilds())

@app.route('/guild/<int:guild_id>/toggle_module', methods=['POST'])
@requires_authorization
def toggle_module(guild_id):
    if not check_guild_permissions(guild_id): return redirect(url_for('dashboard'))
    
    guild_config = bot.data.get_server_config(guild_id)
    enabled_cogs = guild_config.setdefault('enabled_cogs', [])
    
    cog_name = request.form.get('cog_name')
    is_enabled = request.form.get('is_enabled') == 'True'

    if cog_name in MANAGEABLE_COGS:
        if is_enabled:
            if cog_name not in enabled_cogs: enabled_cogs.append(cog_name)
        else:
            if cog_name in enabled_cogs: enabled_cogs.remove(cog_name)
            if cog_name == 'Geburtstage':
                bday_cog = bot.get_cog('Geburtstage')
                if bday_cog:
                    asyncio.run_coroutine_threadsafe(bday_cog.web_cleanup(guild_id), bot.loop)
        
        bot.data.save_server_config(guild_id, guild_config)
        flash(f"Modul '{cog_name}' wurde {'aktiviert' if is_enabled else 'deaktiviert'}.", "success")

    redirect_url = request.form.get('redirect_url', url_for('dashboard'))
    return redirect(redirect_url)

@app.route('/guild/<int:guild_id>/birthday', methods=['GET', 'POST'])
@requires_authorization
def manage_birthdays(guild_id):
    if not check_guild_permissions(guild_id): return redirect(url_for('dashboard'))
    
    guild = bot.get_guild(guild_id)
    guild_config = bot.data.get_server_config(guild_id)
    is_enabled = 'Geburtstage' in guild_config.get('enabled_cogs', [])
    cog = bot.get_cog('Geburtstage')

    if request.method == 'POST' and is_enabled and cog:
        action = request.form.get('action')
        future = None
        if action == 'set_config':
            list_ch_id = int(request.form['list_channel']) if request.form.get('list_channel') else None
            ann_ch_id = int(request.form['announcement_channel']) if request.form.get('announcement_channel') else None
            role_id = int(request.form['birthday_role']) if request.form.get('birthday_role') else None
            future = asyncio.run_coroutine_threadsafe(cog.web_set_config(guild.id, list_ch_id, ann_ch_id, role_id), bot.loop)
        elif action == 'add_bday':
            user_id = int(request.form['user'])
            day = int(request.form['day'])
            month = int(request.form['month'])
            year = int(request.form.get('year')) if request.form.get('year') else None
            future = asyncio.run_coroutine_threadsafe(cog.web_add_birthday(guild.id, user_id, day, month, year), bot.loop)
        elif action == 'remove_bday':
            user_id = int(request.form['user_to_remove'])
            future = asyncio.run_coroutine_threadsafe(cog.web_remove_birthday(guild.id, user_id), bot.loop)
        if future:
            success, message = future.result()
            flash(Markup(message), 'success' if success else 'danger')
        return redirect(url_for('manage_birthdays', guild_id=guild_id))

    guild_bday_data = bot.data.get_guild_data(guild_id, "birthday")
    birthdays = guild_bday_data.get('birthdays', {})
    birthdays_for_template = [{'member': guild.get_member(int(uid)), **data} for uid, data in birthdays.items() if guild.get_member(int(uid))]
    
    return render_template('birthday.html', guild=guild, settings=guild_bday_data, birthdays=birthdays_for_template, is_enabled=is_enabled, admin_guilds=get_admin_guilds())

@app.route('/guild/<int:guild_id>/counting', methods=['GET', 'POST'])
@requires_authorization
def manage_counting(guild_id):
    if not check_guild_permissions(guild_id): return redirect(url_for('dashboard'))
    
    guild = bot.get_guild(guild_id)
    guild_config = bot.data.get_server_config(guild_id)
    is_enabled = 'Zählen' in guild_config.get('enabled_cogs', [])
    cog = bot.get_cog('Zählen')

    if request.method == 'POST' and is_enabled and cog:
        action = request.form.get('action')
        future = None
        if action == 'set_channel':
            channel_id = int(request.form['channel'])
            future = asyncio.run_coroutine_threadsafe(cog.web_set_channel(guild.id, channel_id), bot.loop)
        elif action == 'remove_channel':
            channel_id = int(request.form['channel_to_remove'])
            future = asyncio.run_coroutine_threadsafe(cog.web_remove_channel(guild_id, channel_id), bot.loop)
        elif action == 'set_count':
            channel_id = int(request.form['channel_to_set'])
            number = int(request.form['number'])
            future = asyncio.run_coroutine_threadsafe(cog.web_set_count(guild.id, channel_id, number), bot.loop) # Changed sig
        elif action == 'set_slowmode':
            channel_id = int(request.form['channel_to_set_slowmode'])
            seconds = int(request.form['seconds'])
            future = asyncio.run_coroutine_threadsafe(cog.web_set_slowmode(guild.id, channel_id, seconds), bot.loop)
        elif action == 'add_milestone':
            number = int(request.form['milestone_number'])
            message = request.form['milestone_message']
            future = asyncio.run_coroutine_threadsafe(cog.web_add_milestone(guild.id, number, message), bot.loop)
        elif action == 'remove_milestone':
            number = int(request.form['milestone_to_remove'])
            future = asyncio.run_coroutine_threadsafe(cog.web_remove_milestone(guild.id, number), bot.loop)
        elif action == 'toggle_default_milestone':
            number = int(request.form['milestone_to_toggle'])
            future = asyncio.run_coroutine_threadsafe(cog.web_toggle_default_milestone(guild.id, number), bot.loop)
        if future:
            success, message = future.result()
            flash(Markup(message), 'success' if success else 'danger')
        return redirect(url_for('manage_counting', guild_id=guild_id))

    counting_data = bot.data.get_guild_data(guild_id, "counting")
    active_channels_in_guild = []
    
    # New structure: counting_data is a dict with channel_id as keys
    # Old structure: counting_data has 'channel_id' key
    if 'channel_id' in counting_data:
        # Old structure - migrate to new
        old_channel_id = counting_data.get('channel_id')
        if old_channel_id:
            channel = guild.get_channel(int(old_channel_id))
            if channel:
                active_channels_in_guild.append({
                    'channel': channel, 
                    'data': {
                        'current_number': counting_data.get('current_number', 0),
                        'last_user_id': counting_data.get('last_user_id'),
                        'slowmode': counting_data.get('slowmode', 1)
                    }
                })
    else:
        # New structure - iterate through channel IDs
        for channel_id_str, channel_data in counting_data.items():
            if channel_id_str.isdigit():
                channel = guild.get_channel(int(channel_id_str))
                if channel:
                    active_channels_in_guild.append({'channel': channel, 'data': channel_data})

    guild_milestones = bot.data.get_guild_data(guild_id, "milestones")
    sorted_milestones = sorted([item for item in guild_milestones.items() if item[0].isdigit()], key=lambda item: int(item[0]))
    
    # Load defaults somehow
    default_milestones = [] # Implement if useful, or load from global config
    disabled_defaults = guild_milestones.get("disabled_defaults", [])

    return render_template('counting.html', guild=guild, active_channels=active_channels_in_guild, guild_milestones=sorted_milestones, default_milestones=default_milestones, disabled_default_milestones=disabled_defaults, is_enabled=is_enabled, admin_guilds=get_admin_guilds())

@app.route('/guild/<int:guild_id>/leveling', methods=['GET', 'POST'])
@requires_authorization
def manage_leveling(guild_id):
    if not check_guild_permissions(guild_id): return redirect(url_for('dashboard'))
    
    guild = bot.get_guild(guild_id)
    guild_config = bot.data.get_server_config(guild_id)
    is_enabled = 'Level-System' in guild_config.get('enabled_cogs', [])
    cog = bot.get_cog('Level-System')

    if request.method == 'POST' and is_enabled and cog:
        action = request.form.get('action')
        future = None

        if action == 'toggle_command':
            command_name = request.form.get('command_name')
            future = asyncio.run_coroutine_threadsafe(
                cog.web_toggle_command(guild.id, command_name),
                bot.loop
            )
        elif action == 'set_config':
            xp_per_message = int(request.form.get('xp_per_message', 10))
            xp_cooldown = int(request.form.get('xp_cooldown', 60))
            daily_xp_amount = int(request.form.get('daily_xp_amount', 50))
            log_channel_id = int(request.form.get('log_channel')) if request.form.get('log_channel') else None
            boost_role_tier1_id = int(request.form.get('boost_role1')) if request.form.get('boost_role1') else None
            boost_role_tier2_id = int(request.form.get('boost_role2')) if request.form.get('boost_role2') else None
            boost_role_tier3_id = int(request.form.get('boost_role3')) if request.form.get('boost_role3') else None
            future = asyncio.run_coroutine_threadsafe(cog.web_set_config(guild.id, xp_per_message=xp_per_message, cooldown=xp_cooldown, daily_xp_amount=daily_xp_amount, log_channel_id=log_channel_id, boost_role_tier1_id=boost_role_tier1_id, boost_role_tier2_id=boost_role_tier2_id, boost_role_tier3_id=boost_role_tier3_id), bot.loop)
        elif action == 'add_level_role':
            level = int(request.form['level'])
            role_id = int(request.form['role_id'])
            future = asyncio.run_coroutine_threadsafe(cog.web_manage_level_roles(guild.id, "add", level, role_id), bot.loop)
        elif action == 'remove_level_role':
            level = int(request.form['level_to_remove'])
            future = asyncio.run_coroutine_threadsafe(cog.web_manage_level_roles(guild.id, "remove", level), bot.loop)
        elif action == 'add_no_xp_role':
            role_id = int(request.form['no_xp_role_id'])
            future = asyncio.run_coroutine_threadsafe(cog.web_manage_role_list(guild.id, "no_xp_roles", "add", role_id), bot.loop)
        elif action == 'remove_no_xp_role':
            role_id = int(request.form['role_to_remove'])
            future = asyncio.run_coroutine_threadsafe(cog.web_manage_role_list(guild.id, "no_xp_roles", "remove", role_id), bot.loop)
        elif action == 'add_custom_xp':
            level = int(request.form['custom_level'])
            xp = int(request.form['custom_xp'])
            future = asyncio.run_coroutine_threadsafe(cog.web_manage_custom_xp(guild.id, "add", level, xp), bot.loop)
        elif action == 'remove_custom_xp':
            level = int(request.form['level_to_remove'])
            future = asyncio.run_coroutine_threadsafe(cog.web_manage_custom_xp(guild.id, "remove", level), bot.loop)
        elif action == 'trigger_sync':
            max_msgs = int(request.form['max_msgs']) if request.form.get('max_msgs') else None
            force = 'force_recalc' in request.form
            future = asyncio.run_coroutine_threadsafe(cog.web_trigger_sync(guild.id, force, max_msgs), bot.loop)
        elif action == 'set_user_xp':
            user_id = int(request.form['user_id'])
            xp = int(request.form['xp'])
            level = int(request.form['level'])
            future = asyncio.run_coroutine_threadsafe(cog.web_set_user_xp(guild.id, user_id, xp, level), bot.loop)
        if future:
            success, message = future.result()
            flash(message, 'success' if success else 'danger')
        return redirect(url_for('manage_leveling', guild_id=guild_id))
    
    # Befehlsstatus und andere Daten für das Template holen
    commands_status = {}
    default_xp_progression = {}
    level_config = bot.data.get_guild_data(guild_id, "level_config")


    leaderboard = []
    if is_enabled and cog:
        cog_commands = [cmd for cmd in cog.__cog_app_commands__ if isinstance(cmd, discord.app_commands.Command)]
        guild_level_commands_config = guild_config.get('commands', {}) # Should utilize correct config location if split
        
        for cmd in cog_commands:
            commands_status[cmd.name] = {
                "enabled": guild_level_commands_config.get(cmd.name, True),
                "description": cmd.description
            }
        
        default_xp_progression = {i: cog._get_xp_for_level(i, level_config) for i in range(1, 11)}

        # Fetch leaderboard data directly for the template
        users_data = bot.data.get_guild_data(guild_id, "level_users")
        if users_data:
            for user_id_str, user_data in users_data.items():
                if user_id_str.isdigit():
                    member = guild.get_member(int(user_id_str))
                    if member:
                        leaderboard.append({
                            'member': member,
                            'xp': user_data.get('xp', 0),
                            'level': user_data.get('level', 0)
                        })
            # Sort by XP descending
            leaderboard.sort(key=lambda x: x['xp'], reverse=True)

    return render_template('leveling.html', guild=guild, config=level_config, is_enabled=is_enabled, default_xp_progression=default_xp_progression, commands=commands_status, admin_guilds=get_admin_guilds(), leaderboard=leaderboard)


@app.route('/guild/<int:guild_id>/leveling/leaderboard')
@requires_authorization
def get_leveling_leaderboard(guild_id):
    """API-Endpunkt zum Abrufen des paginierten Leaderboards."""
    if not check_guild_permissions(guild_id):
        return jsonify({"error": "Unauthorized"}), 403

    guild = bot.get_guild(guild_id)
    if not guild:
        return jsonify({"error": "Guild not found"}), 404

    cog = bot.get_cog('Level-System')
    if not cog:
        return jsonify({"error": "Level-System cog not found"}), 500

    if not hasattr(cog, 'web_get_paginated_leaderboard'):
        return jsonify({"error": "Bot-Cog ist veraltet. Bitte den Bot-Entwickler kontaktieren."}), 501

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    if per_page > 100: per_page = 100 # Limit per_page

    future = asyncio.run_coroutine_threadsafe(
        cog.web_get_paginated_leaderboard(guild.id, page, per_page),
        bot.loop
    )
    
    try:
        # Ein Timeout stellt sicher, dass die Anfrage nicht ewig hängt.
        leaderboard_data = future.result(timeout=20)
        return jsonify(leaderboard_data)
    except asyncio.TimeoutError:
        return jsonify({"error": "Timeout bei der Erstellung des Leaderboards."}), 504
    except Exception as e:
        print(f"Fehler beim Abrufen des paginierten Leaderboards: {e}")
        return jsonify({"error": "Ein interner Fehler ist aufgetreten."}), 500

@app.route('/guild/<int:guild_id>/tickets', methods=['GET', 'POST'])
@requires_authorization
def manage_tickets(guild_id):
    if not check_guild_permissions(guild_id):
        return redirect(url_for('dashboard'))

    guild = bot.get_guild(guild_id)
    guild_config = bot.data.get_server_config(guild_id)
    is_enabled = 'Ticket-System' in guild_config.get('enabled_cogs', [])
    cog = bot.get_cog('Ticket-System')
    
    if request.method == 'POST' and is_enabled and cog:
        action = request.form.get('action')
        future = None

        if action == 'set_config':
            ticket_channel_id = int(request.form['ticket_channel']) if request.form.get('ticket_channel') else None
            ticket_kategorie_id = int(request.form['ticket_category']) if request.form.get('ticket_category') else None
            log_channel_id = int(request.form.get('log_channel')) if request.form.get('log_channel') else None
            max_tickets_per_user = int(request.form.get('max_tickets_per_user', 1))
            future = asyncio.run_coroutine_threadsafe(cog.web_set_config(guild_id, ticket_channel_id, ticket_kategorie_id, log_channel_id, max_tickets_per_user), bot.loop)
        
        elif action == 'add_support_role':
            role_id = int(request.form.get('role_id'))
            future = asyncio.run_coroutine_threadsafe(cog.web_add_support_role(guild_id, role_id), bot.loop)

        elif action == 'remove_support_role':
            role_id_to_remove = int(request.form.get('role_id_to_remove'))
            future = asyncio.run_coroutine_threadsafe(cog.web_remove_support_role(guild_id, role_id_to_remove), bot.loop)

        elif action == 'add_reason':
            name = request.form.get('reason_name')
            desc = request.form.get('reason_desc')
            emoji = request.form.get('reason_emoji')
            role_ids = request.form.getlist('reason_roles')  # Get multiple selected roles
            role_ids = [int(rid) for rid in role_ids if rid]  # Convert to integers
            future = asyncio.run_coroutine_threadsafe(cog.web_add_reason(guild_id, name, desc, emoji, role_ids), bot.loop)

        elif action == 'remove_reason':
            name_to_remove = request.form.get('reason_name_to_remove')
            future = asyncio.run_coroutine_threadsafe(cog.web_remove_reason(guild_id, name_to_remove), bot.loop)

        elif action == 'add_reason_role':
            reason_name = request.form.get('reason_name')
            role_id = int(request.form.get('role_id'))
            future = asyncio.run_coroutine_threadsafe(cog.web_add_reason_role(guild_id, reason_name, role_id), bot.loop)
        
        elif action == 'remove_reason_role':
            reason_name = request.form.get('reason_name')
            role_id_to_remove = int(request.form.get('role_id_to_remove'))
            future = asyncio.run_coroutine_threadsafe(cog.web_remove_reason_role(guild_id, reason_name, role_id_to_remove), bot.loop)

        if future:
            success, message = future.result()
            flash(message, 'success' if success else 'danger')

        return redirect(url_for('manage_tickets', guild_id=guild_id))

    guild_ticket_config = bot.data.get_guild_data(guild_id, "ticket_config")
    # Fix: ensure support_roles is always a list
    if "support_roles" in guild_ticket_config and not isinstance(guild_ticket_config["support_roles"], list):
        guild_ticket_config["support_roles"] = [guild_ticket_config["support_roles"]]
    return render_template('tickets.html', guild=guild, settings=guild_ticket_config, is_enabled=is_enabled, admin_guilds=get_admin_guilds())


@app.route('/guild/<int:guild_id>/twitch', methods=['GET', 'POST'])
@requires_authorization
def manage_twitch(guild_id):
    if not check_guild_permissions(guild_id):
        flash("Du hast keine Berechtigung für diesen Server.", "danger")
        return redirect(url_for('dashboard'))

    guild = bot.get_guild(guild_id)
    guild_config = bot.data.get_server_config(guild_id)

    if request.method == 'POST':
        # This POST handler is for the multi-streamer alert form
        cog = bot.get_cog('Twitch')
        is_enabled = 'Twitch' in guild_config.get('enabled_cogs', [])
        if not is_enabled or not cog:
            flash("Das Twitch-Modul (Multi-Stream) ist nicht aktiv.", "danger")
            return redirect(url_for('manage_twitch', guild_id=guild_id))

        action = request.form.get('action')
        future = None
        if action == 'set_multi_stream_config':
            channel_id_str = request.form.get('multi_channel_id')
            channel_id = int(channel_id_str) if channel_id_str else None
            future = asyncio.run_coroutine_threadsafe(cog.web_set_feed_config(guild_id, channel_id), bot.loop)
        elif action == 'set_streamer_command_config':
            role_id_str = request.form.get('streamer_role_id')
            role_id = int(role_id_str) if role_id_str else None
            future = asyncio.run_coroutine_threadsafe(cog.web_set_streamer_command_role(guild_id, role_id), bot.loop)
        elif action == 'add_streamer':
            streamer_name = request.form.get('streamer_name')
            future = asyncio.run_coroutine_threadsafe(cog.web_add_streamer(guild_id, streamer_name), bot.loop)
        elif action == 'remove_streamer':
            streamer_name = request.form.get('streamer_name')
            future = asyncio.run_coroutine_threadsafe(cog.web_remove_streamer(guild_id, streamer_name), bot.loop)
        
        if future:
            success, message = future.result()
            flash(message, 'success' if success else 'danger')
        return redirect(url_for('manage_twitch', guild_id=guild_id))

    # GET request: Gather data for all three modules
    # 1. Multi-Streamer Alert data
    multi_stream_is_enabled = 'Twitch' in guild_config.get('enabled_cogs', [])
    multi_stream_config = bot.data.get_guild_data(guild_id, "streamers")

    # 2. Single-Streamer Status data
    single_stream_is_enabled = 'Twitch-Live-Alert' in guild_config.get('enabled_cogs', [])
    single_stream_config = bot.data.get_guild_data(guild_id, "twitch_alerts")

    # 3. Twitch Clips data
    clips_is_enabled = 'Twitch-Clips' in guild_config.get('enabled_cogs', [])
    clips_config = bot.data.get_guild_data(guild_id, "twitch_clips")

    return render_template('twitch_tools.html',
                           guild=guild, 
                           admin_guilds=get_admin_guilds(),
                           multi_stream_is_enabled=multi_stream_is_enabled,
                           streamers_data=multi_stream_config,
                           single_stream_is_enabled=single_stream_is_enabled,
                           single_stream_config=single_stream_config,
                           clips_is_enabled=clips_is_enabled,
                           clips_config=clips_config)


# --- Temp-Channel Web-Route ---
@app.route('/guild/<int:guild_id>/temp_channel', methods=['GET', 'POST'])
@requires_authorization
def manage_temp_channel(guild_id):
    """Verwaltet die Temp-Channel-Einstellungen für einen Server."""
    if not check_guild_permissions(guild_id):
        flash("Du hast keine Berechtigung, diese Seite anzuzeigen.", "error")
        return redirect(url_for("dashboard"))

    guild = bot.get_guild(guild_id)
    if not guild:
        return redirect(url_for('dashboard'))

    guild_config = bot.data.get_server_config(guild_id)
    is_enabled = 'Temp-Channel' in guild_config.get('enabled_cogs', [])

    temp_data = bot.data.get_guild_data(guild_id, "temp_channels")
    temp_data.setdefault('config', {})
    temp_data.setdefault('active_channels', {})

    if request.method == 'POST' and is_enabled:
        # Daten aus dem Formular holen
        trigger_channel_id_str = request.form.get('trigger_channel_id')
        trigger_channel_id = int(trigger_channel_id_str) if trigger_channel_id_str else None
        channel_name_format = request.form.get('channel_name_format', '🔊 {user}\'s Raum')

        # 1. Daten direkt im Speicher des Bots aktualisieren
        config = temp_data['config']
        config['trigger_channel_id'] = trigger_channel_id
        config['channel_name_format'] = channel_name_format

        # 2. Speicher
        bot.data.save_guild_data(guild_id, "temp_channels", temp_data)
        
        flash("Temp-Channel Einstellungen erfolgreich gespeichert!", "success")
        return redirect(url_for('manage_temp_channel', guild_id=guild_id))

    # Konfiguration für das Template laden
    config_for_template = temp_data.get('config', {})
    return render_template('temp_channel.html', guild=guild, config=config_for_template, is_enabled=is_enabled, admin_guilds=get_admin_guilds())


@app.route('/guild/<int:guild_id>/twitch_clips', methods=['GET', 'POST'])
@requires_authorization
def manage_twitch_clips(guild_id):
    if not check_guild_permissions(guild_id):
        flash("Du hast keine Berechtigung für diesen Server.", "danger")
        return redirect(url_for('dashboard'))

    if request.method == 'GET':
        return redirect(url_for('manage_twitch', guild_id=guild_id), code=301)

    # POST logic
    cog = bot.get_cog('Twitch-Clips')
    guild_config = bot.data.get_server_config(guild_id)
    is_enabled = 'Twitch-Clips' in guild_config.get('enabled_cogs', [])
    if not is_enabled or not cog:
        flash("Das Twitch-Clips-Modul ist nicht aktiv.", "danger")
        return redirect(url_for('manage_twitch', guild_id=guild_id))

    action = request.form.get('action')
    future = None
    if action == 'set_config':
        channel_id_str = request.form.get('channel_id')
        channel_id = int(channel_id_str) if channel_id_str else None
        streamer_name = request.form.get('streamer_name')
        future = asyncio.run_coroutine_threadsafe(cog.web_set_config(guild_id, streamer_name, channel_id), bot.loop)
    elif action == 'add_channel':
        streamer_name = request.form.get('streamer_name')
        future = asyncio.run_coroutine_threadsafe(cog.web_add_channel(guild_id, streamer_name), bot.loop)
    elif action == 'remove_channel':
        streamer_name = request.form.get('streamer_name')
        future = asyncio.run_coroutine_threadsafe(cog.web_remove_channel(guild_id, streamer_name), bot.loop)

    if future:
        success, message = future.result()
        flash(message, 'success' if success else 'danger')
    
    return redirect(url_for('manage_twitch', guild_id=guild_id))


@app.route('/guild/<int:guild_id>/streak', methods=['GET'])
@requires_authorization
def manage_streak(guild_id):
    if not check_guild_permissions(guild_id):
        flash("Du hast keine Berechtigung für diesen Server.", "danger")
        return redirect(url_for('dashboard'))

    guild = bot.get_guild(guild_id)
    guild_config = bot.data.get_server_config(guild_id)
    is_enabled = 'Streak' in guild_config.get('enabled_cogs', [])
    cog = bot.get_cog('Streak')

    streaks_for_template = []
    if is_enabled and cog:
        future = asyncio.run_coroutine_threadsafe(cog.web_get_streaks(guild_id), bot.loop)
        streaks_for_template = future.result()

    return render_template('streak.html',
                           guild=guild,
                           is_enabled=is_enabled,
                           streaks=streaks_for_template,
                           admin_guilds=get_admin_guilds())


@app.route('/guild/<int:guild_id>/twitch_status', methods=['GET', 'POST'])
@requires_authorization
def manage_twitch_status(guild_id):
    if not check_guild_permissions(guild_id):
        flash("Du hast keine Berechtigung für diesen Server.", "danger")
        return redirect(url_for('dashboard'))

    # GET requests should go to the unified page
    if request.method == 'GET':
        return redirect(url_for('manage_twitch', guild_id=guild_id), code=301)

    # POST logic remains
    cog = bot.get_cog('Twitch-Live-Alert')
    guild_config = bot.data.get_server_config(guild_id)
    is_enabled = 'Twitch-Live-Alert' in guild_config.get('enabled_cogs', [])

    if not is_enabled or not cog:
        flash("Das Twitch Live Alert-Modul ist nicht aktiv.", "danger")
        return redirect(url_for('manage_twitch', guild_id=guild_id))

    action = request.form.get('action')
    future = None
    if action == 'set_config':
        twitch_user = request.form.get('twitch_user')
        role_id_str = request.form.get('role_id')
        role_id = int(role_id_str) if role_id_str else None
        future = asyncio.run_coroutine_threadsafe(cog.web_set_config(guild_id, twitch_user, role_id), bot.loop)
    elif action == 'reset':
        future = asyncio.run_coroutine_threadsafe(cog.web_reset_config(guild_id), bot.loop)

    if future:
        success, message = future.result()
        flash(message, 'success' if success else 'danger')

    # After POST, redirect to the unified page
    return redirect(url_for('manage_twitch', guild_id=guild_id))


@app.route('/guild/<int:guild_id>/gatekeeper', methods=['GET', 'POST'])
@requires_authorization
def manage_gatekeeper(guild_id):
    if not check_guild_permissions(guild_id):
        flash("Du hast keine Berechtigung für diesen Server.", "danger")
        return redirect(url_for('dashboard'))

    # GET-Anfragen auf die neue, kombinierte Sicherheitsseite umleiten
    if request.method == 'GET':
        return redirect(url_for('manage_guard', guild_id=guild_id), code=301)

    # Die POST-Logik bleibt hier, um Gatekeeper-Aktionen zu verarbeiten
    guild = bot.get_guild(guild_id)
    guild_config = bot.data.get_server_config(guild_id)
    is_enabled = 'Gatekeeper' in guild_config.get('enabled_cogs', [])
    cog = bot.get_cog('Gatekeeper')

    if not is_enabled or not cog:
        flash("Das Gatekeeper-Modul ist nicht aktiv.", "danger")
        return redirect(url_for('manage_guard', guild_id=guild_id))

    action = request.form.get('action')
    future = None

    if action == 'reset':
        future = asyncio.run_coroutine_threadsafe(cog.web_reset_config(guild_id), bot.loop)
    elif action == 'set_config':
        role_id_str = request.form.get('required_role_id')
        role_id = int(role_id_str) if role_id_str else None
        time_limit = int(request.form.get('time_limit_minutes', 5))
        kick_message = request.form.get('kick_message', "Du wurdest vom Server entfernt, da du die Verifizierung nicht innerhalb der vorgegebenen Zeit abgeschlossen hast.")
        future = asyncio.run_coroutine_threadsafe(cog.web_set_config(guild_id, role_id, time_limit, kick_message), bot.loop)
    
    if future:
        success, message = future.result()
        flash(message, 'success' if success else 'danger')

    # Nach der Aktion zurück zur kombinierten Sicherheitsseite umleiten
    return redirect(url_for('manage_guard', guild_id=guild_id))

@app.route('/guild/<int:guild_id>/guard', methods=['GET', 'POST'])
@requires_authorization
def manage_guard(guild_id):
    if not check_guild_permissions(guild_id):
        flash("Du hast keine Berechtigung für diesen Server.", "danger")
        return redirect(url_for('dashboard'))
    
    guild = bot.get_guild(guild_id)
    guild_config = bot.data.get_server_config(guild_id)

    if request.method == 'POST':
        # Dieser Block verarbeitet nur noch die Guard-Formular-POSTs
        guard_is_enabled = 'Guard' in guild_config.get('enabled_cogs', [])
        guard_cog = bot.get_cog('Guard')
        if not guard_is_enabled or not guard_cog:
            flash("Das Guard-Modul ist nicht aktiv.", "danger")
            return redirect(url_for('manage_guard', guild_id=guild_id))

        # Daten aus dem Formular holen
        action_type = request.form.get('action_type', 'none')
        account_age_days = int(request.form.get('account_age_days', 7))
        kick_message = request.form.get('kick_message', "Dein Account ist zu neu, um diesem Server beizutreten.")
        role_id_str = request.form.get('role_id')
        role_id = int(role_id_str) if role_id_str else None
        log_channel_id_str = request.form.get('log_channel_id')
        log_channel_id = int(log_channel_id_str) if log_channel_id_str else None

        future = asyncio.run_coroutine_threadsafe(
            guard_cog.web_set_config(
                guild_id, 
                action_type, 
                account_age_days, 
                kick_message, 
                role_id, 
                log_channel_id
            ), 
            bot.loop
        )
        success, message = future.result()
        flash(message, 'success' if success else 'danger')
        return redirect(url_for('manage_guard', guild_id=guild_id))

    # --- Daten für die GET-Anfrage sammeln (Guard & Gatekeeper) ---
    # Guard Daten
    guard_is_enabled = 'Guard' in guild_config.get('enabled_cogs', [])
    guard_config = bot.data.get_guild_data(guild_id, "guard")
    
    # Gatekeeper Daten
    gatekeeper_is_enabled = 'Gatekeeper' in guild_config.get('enabled_cogs', [])
    gatekeeper_config = bot.data.get_guild_data(guild_id, "gatekeeper")
    pending_members = []

    # Global Ban Daten
    global_ban_is_enabled = 'Global-Ban' in guild_config.get('enabled_cogs', [])
    global_ban_config = bot.data.get_guild_data(guild_id, "global_ban")

    if gatekeeper_is_enabled:
        gatekeeper_cog = bot.get_cog('Gatekeeper')
        if gatekeeper_cog:
            future = asyncio.run_coroutine_threadsafe(gatekeeper_cog.web_get_pending_members(guild_id), bot.loop)
            pending_members = future.result()

    return render_template('guard.html', guild=guild, admin_guilds=get_admin_guilds(),
                           guard_config=guard_config, guard_is_enabled=guard_is_enabled,
                           gatekeeper_config=gatekeeper_config, gatekeeper_is_enabled=gatekeeper_is_enabled,
                           pending_members=pending_members,
                           global_ban_config=global_ban_config, global_ban_is_enabled=global_ban_is_enabled)

@app.route('/guild/<int:guild_id>/global_ban', methods=['GET', 'POST'])
@requires_authorization
def manage_global_ban(guild_id):
    if not check_guild_permissions(guild_id):
        flash("Du hast keine Berechtigung für diesen Server.", "danger")
        return redirect(url_for('dashboard'))

    # GET-Anfragen auf die neue, kombinierte Sicherheitsseite umleiten
    if request.method == 'GET':
        return redirect(url_for('manage_guard', guild_id=guild_id), code=301)

    guild = bot.get_guild(guild_id)
    guild_config = bot.data.get_server_config(guild_id)
    is_enabled = 'Global-Ban' in guild_config.get('enabled_cogs', [])
    cog = bot.get_cog('Global-Ban')

    if request.method == 'POST':
        if not is_enabled or not cog:
            flash("Das Global-Ban-Modul ist nicht aktiv.", "danger")
            return redirect(url_for('manage_guard', guild_id=guild_id))

        log_channel_id_str = request.form.get('log_channel_id')
        log_channel_id = int(log_channel_id_str) if log_channel_id_str else None
        
        future = asyncio.run_coroutine_threadsafe(
            cog.web_set_config(guild_id, log_channel_id),
            bot.loop
        )
        success, message = future.result()
        flash(message, 'success' if success else 'danger')
    
    return redirect(url_for('manage_guard', guild_id=guild_id))

@app.route('/guild/<int:guild_id>/wrapped', methods=['GET', 'POST'])
@requires_authorization
def manage_wrapped(guild_id):
    if not check_guild_permissions(guild_id):
        flash("Du hast keine Berechtigung für diesen Server.", "danger")
        return redirect(url_for('dashboard'))

    guild = bot.get_guild(guild_id)
    guild_config = bot.data.get_server_config(guild_id)
    is_enabled = 'Wrapped' in guild_config.get('enabled_cogs', [])
    cog = bot.get_cog('Wrapped')

    if request.method == 'POST':
        if not cog: # Sollte eigentlich nicht passieren, wenn geladen
             flash("Das Wrapped-Modul ist nicht geladen.", "danger")
             return redirect(url_for('manage_wrapped', guild_id=guild_id))

        action = request.form.get('action')
        future = None
        
        if action == 'toggle_commands':
            enabled = request.form.get('enabled') == 'True'
            future = asyncio.run_coroutine_threadsafe(cog.web_set_command_status(guild_id, enabled), bot.loop)
        
        elif action == 'send_button':
            channel_id_str = request.form.get('channel_id')
            custom_text = request.form.get('custom_text', 'Schau dir jetzt deinen persönlichen Jahresrückblick an!')
            if channel_id_str:
                future = asyncio.run_coroutine_threadsafe(cog.web_send_wrapped_button(guild_id, int(channel_id_str), custom_text), bot.loop)
            else:
                flash("Kein Kanal ausgewählt.", "danger")
                return redirect(url_for('manage_wrapped', guild_id=guild_id))

        elif action == 'create_snapshot':
            future = asyncio.run_coroutine_threadsafe(cog.web_create_snapshot(guild_id), bot.loop)
        
        elif action == 'toggle_web_links':
            enabled = request.form.get('enabled') == 'True'
            future = asyncio.run_coroutine_threadsafe(cog.web_toggle_web_links(guild_id, enabled), bot.loop)

        elif action == 'set_web_base_url':
            url = request.form.get('web_base_url')
            future = asyncio.run_coroutine_threadsafe(cog.web_set_base_url(guild_id, url), bot.loop)

        if future:
            success, message = future.result()
            flash(message, 'success' if success else 'danger')
        
        return redirect(url_for('manage_wrapped', guild_id=guild_id))

    wrapped_config = {"user_commands_enabled": False}
    server_stats = {} # Live Stats
    snapshot_info = None # Snapshot info

    if cog:
        # Config laden
        future_cfg = asyncio.run_coroutine_threadsafe(cog.web_get_config(guild_id), bot.loop)
        wrapped_config = future_cfg.result()

        # Live Stats laden
        future_live = asyncio.run_coroutine_threadsafe(cog.web_get_live_stats(guild_id), bot.loop)
        server_stats = future_live.result()

        # Snapshot Info laden
        future_snap = asyncio.run_coroutine_threadsafe(cog.web_get_snapshot_info(guild_id), bot.loop)
        snapshot_info = future_snap.result()

    return render_template('wrapped.html', 
                           guild=guild, 
                           admin_guilds=get_admin_guilds(),
                           is_enabled=is_enabled,
                           wrapped_config=wrapped_config,
                           server_stats=server_stats,
                           snapshot_info=snapshot_info)

@app.route('/wrapped/<int:guild_id>/<token>')
def view_wrapped_public(guild_id, token):
    """Öffentliche Wrapped-Ansicht mit zeitlich begrenztem Token."""
    cog = bot.get_cog('Wrapped')
    if not cog:
        return render_template('error.html', message="Wrapped-Modul nicht verfügbar."), 404
    
    # Validate token
    token_data = cog.validate_wrapped_web_token(guild_id, token)
    if not token_data:
        return render_template('error.html', message="Dieser Link ist ungültig oder abgelaufen. Links sind nur 30 Minuten gültig."), 404
    
    # Get guild and user data
    guild = bot.get_guild(guild_id)
    if not guild:
        return render_template('error.html', message="Server nicht gefunden."), 404
    
    user_id = token_data["user_id"]
    year = token_data["year"]
    
    # Get snapshot data
    data = cog._get_snapshot_data(guild_id, year)
    if not data:
        return render_template('error.html', message="Keine Wrapped-Daten verfügbar."), 404
    
    user_data = data.get("users", {}).get(str(user_id))
    if not user_data:
        return render_template('error.html', message="Keine Daten für diesen Benutzer verfügbar."), 404
    
    # Get user info
    member = guild.get_member(user_id)
    user_name = member.display_name if member else f"User {user_id}"
    user_avatar = member.display_avatar.url if member else None
    
    # Calculate expiry time remaining
    import time
    time_remaining = int((token_data["expires_at"] - time.time()) / 60)  # minutes
    
    # Prepare data for template
    wrapped_data = {
        "username": user_name,
        "user_avatar": user_avatar,
        "year": year,
        "guild_name": guild.name,
        "guild_icon": guild.icon.url if guild.icon else None,
        "total_messages": user_data.get('total_messages', 0),
        "voice_minutes": user_data.get('voice_minutes', 0),
        "voice_hours": round(user_data.get('voice_minutes', 0) / 60, 1),
        "top_channel": None,
        "top_channel_name": None,
        "top_voice_channel": None,
        "top_emoji": None,
        "snapshot_date": data.get('snapshot_date', 'Unbekannt'),
        "time_remaining": time_remaining,
        "tickets_processed": user_data.get('tickets_processed', 0),
        "best_buddy_id": None,
        "best_buddy_count": 0
    }
    
    # Top channel
    if user_data.get('top_channel'):
        fav_channel_id = max(user_data['top_channel'], key=user_data['top_channel'].get)
        count = user_data['top_channel'][fav_channel_id]
        channel = guild.get_channel(int(fav_channel_id))
        wrapped_data["top_channel"] = fav_channel_id
        wrapped_data["top_channel_name"] = channel.name if channel else f"Kanal {fav_channel_id}"
    
    # Top voice channel
    if user_data.get('top_voice_channel'):
        fav_v_channel_id = max(user_data['top_voice_channel'], key=user_data['top_voice_channel'].get)
        mins = user_data['top_voice_channel'][fav_v_channel_id]
        channel = guild.get_channel(int(fav_v_channel_id))
        wrapped_data["top_voice_channel"] = {
            "name": channel.name if channel else f"Kanal {fav_v_channel_id}",
            "minutes": mins
        }
    
    # Top emoji
    if user_data.get('top_emojis'):
        fav_emoji_key = max(user_data['top_emojis'], key=user_data['top_emojis'].get)
        count = user_data['top_emojis'][fav_emoji_key]
        
        if fav_emoji_key.startswith("custom:"):
            emoji_id = fav_emoji_key.replace("custom:", "")
            emoji = bot.get_emoji(int(emoji_id))
            emoji_str = str(emoji) if emoji else "❓"
        elif fav_emoji_key.startswith("unicode:"):
            emoji_str = fav_emoji_key.replace("unicode:", "")
        else:
            emoji_str = "❓"
        
        wrapped_data["top_emoji"] = emoji_str
    
    # Best Buddy
    interactions = user_data.get('interactions', {})
    if interactions:
        best_buddy_id = max(interactions, key=interactions.get)
        interaction_count = interactions[best_buddy_id]
        
        if interaction_count > 0:
            buddy_member = guild.get_member(int(best_buddy_id))
            wrapped_data["best_buddy_id"] = buddy_member.display_name if buddy_member else f"User {best_buddy_id}"
            wrapped_data["best_buddy_avatar"] = buddy_member.display_avatar.url if buddy_member else None
            wrapped_data["best_buddy_count"] = interaction_count
    
    # Streak
    # Streak
    streak_data = bot.data.get_guild_data(guild_id, "streaks")
    
    # Handle both potential formats (sometimes streaks are simple ints, usually dictionaries)
    if streak_data and isinstance(streak_data, dict):
        user_streak = streak_data.get(str(user_id), {})
        if isinstance(user_streak, dict):
            current_streak = user_streak.get("current_streak", 0)
            wrapped_data["streak_since"] = user_streak.get("last_message_date", "")
        else:
            # Fallback if structure is weird or old data
            current_streak = 0
            wrapped_data["streak_since"] = ""
    else:
        current_streak = 0
        wrapped_data["streak_since"] = ""

    wrapped_data["streak"] = current_streak

    return render_template('wrapped_public.html', data=wrapped_data)

@app.route('/guild/<int:guild_id>/moderation', methods=['GET', 'POST'])
@requires_authorization
def manage_moderation(guild_id):
    guild = bot.get_guild(guild_id)
    if not guild:
        return redirect(url_for('dashboard'))

    if not check_guild_permissions(guild_id):
        return redirect(url_for('dashboard'))

    guild_config = bot.data.get_server_config(guild_id)
    is_enabled = 'Moderation' in guild_config.get('enabled_cogs', [])
    cog = bot.get_cog("Moderation")

    if request.method == 'POST' and is_enabled and cog:
        action = request.form.get('action')
        if action == 'toggle_command':
            command_name = request.form.get('command_name')
            
            future = asyncio.run_coroutine_threadsafe(
                cog.web_toggle_command(guild.id, command_name),
                bot.loop
            )
            success, message = future.result()
            flash(message, 'success' if success else 'danger')
        
        return redirect(url_for('manage_moderation', guild_id=guild_id))

    # Daten für die Template-Darstellung holen
    commands_status = {}
    if is_enabled and cog:
        # Hole alle Slash-Befehle aus dem Cog
        # Korrektur basierend auf dem Traceback: __cog_app_commands__ verwenden
        cog_commands = [cmd for cmd in cog.__cog_app_commands__ if isinstance(cmd, discord.app_commands.Command)]
        
        # Lade die aktuellen Einstellungen für diesen Server
        guild_mod_commands_config = guild_config.get('cogs', {}).get('Moderation', {}).get('commands', {})
        
        for cmd in cog_commands:
            # Der Status ist 'True' (aktiviert), wenn kein spezifischer Eintrag vorhanden ist
            commands_status[cmd.name] = {
                "enabled": guild_mod_commands_config.get(cmd.name, True),
                "description": cmd.description
            }

    return render_template('moderation.html', 
                           guild=guild, 
                           is_enabled=is_enabled, 
                           commands=commands_status,
                           admin_guilds=get_admin_guilds())


# --- BOT-EVENTS & START ---
@bot.event
async def on_ready():
    """Wird ausgeführt, wenn der Bot erfolgreich mit Discord verbunden ist."""
    print(f"✅ Bot ist eingeloggt als {bot.user}")
    print(f"🌐 Web-Oberfläche läuft auf http://0.0.0.0:5002")
    
    # Konfiguration für alle Server sicherstellen, dass Standard-Cogs aktiv sind
    print("-> Überprüfe Server-Konfigurationen auf Standard-Cogs...")
    default_cogs_to_enable = ["Utility", "Settings", "Global-Ban"]
    any_guild_updated = False
    for guild in bot.guilds:
        # Nutzung des DataManagers
        guild_config = bot.data.get_server_config(guild.id)
        if not guild_config:
            guild_config = {"prefix": "!", "enabled_cogs": []}
        
        enabled_cogs = guild_config.setdefault('enabled_cogs', [])
        
        local_updated = False
        for cog_name in default_cogs_to_enable:
            if cog_name not in enabled_cogs:
                enabled_cogs.append(cog_name)
                local_updated = True
        
        if local_updated:
            bot.data.save_server_config(guild.id, guild_config)
            any_guild_updated = True
    
    if any_guild_updated:
        print("-> Server-Konfigurationen wurden mit Standard-Cogs aktualisiert.")
        
    # Lade alle Cogs aus dem 'cogs' Verzeichnis
    cogs_to_load = [
        'cogs.settings', 'cogs.utility', 'cogs.birthday', 'cogs.counting', 
        'cogs.level_system', 'cogs.moderation', 'cogs.ticket_system', 'cogs.twitch', 
        'cogs.twitch_live_alert', 'cogs.temp_channel', 'cogs.twitch_clips', 'cogs.streak', 
        'cogs.gatekeeper', 'cogs.guard', 'cogs.global_ban', 'cogs.maintenance', 'cogs.wrapped',
        'cogs.lfg', 'cogs.monthly_stats', 'cogs.leaderboard_display', 'cogs.info'
    ]
    for cog in cogs_to_load:
        try:
            await bot.load_extension(cog)
            print(f"-> Cog '{cog}' geladen.")
        except commands.ExtensionAlreadyLoaded:
            pass # Ignoriere, falls schon geladen (z.B. bei reconnect)
        except Exception as e:
            print(f"Fehler beim Laden von Cog '{cog}': {e}")

    # Synchronisiere die Slash-Befehle, nachdem der Bot bereit ist
    try:
        synced = await bot.tree.sync()
        print(f"-> {len(synced)} Slash-Befehl(e) synchronisiert.")
    except Exception as e:
        print(f"Fehler beim Synchronisieren der Befehle: {e}")

@bot.event
async def on_guild_join(guild):
    # Bei Join neue Config erstellen
    default_cogs = ["Utility", "Settings", "Global-Ban"]
    initial_config = {'prefix': '!', 'welcome_channel_id': None, 'enabled_cogs': default_cogs}
    bot.data.save_server_config(guild.id, initial_config)
    print(f'Server "{guild.name}" beigetreten. Standardeinstellungen erstellt.')

import atexit

# ... existing imports ...
from werkzeug.middleware.proxy_fix import ProxyFix

# ... (omitted lines) ...


@app.route('/guild/<int:guild_id>/lfg', methods=['GET', 'POST'])
@requires_authorization
def manage_lfg(guild_id):
    if not check_guild_permissions(guild_id):
        flash("Du hast keine Berechtigung für diesen Server.", "danger")
        return redirect(url_for('dashboard'))

    guild = bot.get_guild(guild_id)
    guild_config = bot.data.get_server_config(guild_id)
    is_enabled = 'LFG' in guild_config.get('enabled_cogs', []) or 'Mitspieler-Suche' in guild_config.get('enabled_cogs', [])

    if request.method == 'POST':
        cog = bot.get_cog('LFG') or bot.get_cog('Mitspieler-Suche')
        if not is_enabled or not cog:
            flash("Das LFG-Modul ist nicht aktiv.", "danger")
            return redirect(url_for('manage_lfg', guild_id=guild_id))

        action = request.form.get('action')
        future = None

        if action == 'set_config':
            start_channel_id = int(request.form.get('start_channel')) if request.form.get('start_channel') else None
            lobby_channel_id = int(request.form.get('lobby_channel')) if request.form.get('lobby_channel') else None
            participation_role_id = int(request.form.get('participation_role')) if request.form.get('participation_role') else None
            max_searches = int(request.form.get('max_searches', 3))
            display_mode = request.form.get('display_mode', 'classic')
            lfg_forum_id = int(request.form.get('lfg_forum_id')) if request.form.get('lfg_forum_id') else None
            
            future = asyncio.run_coroutine_threadsafe(
                cog.web_set_config(guild_id, start_channel_id, lobby_channel_id, participation_role_id, max_searches, display_mode, lfg_forum_id),
                bot.loop
            )

        if future:
            success, message = future.result()
            flash(message, 'success' if success else 'danger')

        return redirect(url_for('manage_lfg', guild_id=guild_id))

    settings = bot.data.get_guild_data(guild_id, "lfg_config")
    return render_template('lfg.html', guild=guild, settings=settings, is_enabled=is_enabled, admin_guilds=get_admin_guilds())


@app.route('/guild/<int:guild_id>/leaderboard_settings', methods=['GET', 'POST'])
@requires_authorization
def manage_leaderboard_settings(guild_id):
    """Verwaltet die Leaderboard-Einstellungen."""
    if not check_guild_permissions(guild_id):
        flash("Du hast keine Berechtigung für diesen Server.", "danger")
        return redirect(url_for('dashboard'))

    guild = bot.get_guild(guild_id)
    if not guild:
        flash("Server nicht gefunden.", "danger")
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'set_channel':
            # Save leaderboard channel setting
            leaderboard_data = bot.data.get_guild_data(guild_id, "leaderboard_config")
            channel_id_str = request.form.get('leaderboard_channel_id')
            channel_id = int(channel_id_str) if channel_id_str else None
            display_mode = request.form.get('display_mode', 'single')
            
            leaderboard_data['leaderboard_channel_id'] = channel_id
            leaderboard_data['display_mode'] = display_mode
            bot.data.save_guild_data(guild_id, "leaderboard_config", leaderboard_data)
            
            flash("Leaderboard-Einstellungen gespeichert!", "success")
        
        elif action == 'setup_interactive':
            # Setup interactive leaderboard display
            leaderboard_data = bot.data.get_guild_data(guild_id, "leaderboard_config")
            channel_id = leaderboard_data.get('leaderboard_channel_id')
            
            if not channel_id:
                flash("Bitte konfiguriere zuerst einen Leaderboard-Channel!", "danger")
                return redirect(url_for('manage_leaderboard_settings', guild_id=guild_id))
            
            cog = bot.get_cog('LeaderboardDisplay')
            if not cog:
                flash("Leaderboard-Display-Modul nicht geladen!", "danger")
                return redirect(url_for('manage_leaderboard_settings', guild_id=guild_id))
            
            future = asyncio.run_coroutine_threadsafe(
                cog.web_setup_leaderboard(guild_id, channel_id),
                bot.loop
            )
            
            try:
                success, message = future.result(timeout=10)
                if success:
                    flash(message, "success")
                else:
                    flash(message, "danger")
            except Exception as e:
                flash(f"Fehler: {str(e)}", "danger")
        
        elif action == 'set_summary_channel':
            # Save monthly summary channel setting
            leaderboard_data = bot.data.get_guild_data(guild_id, "leaderboard_config")
            channel_id_str = request.form.get('monthly_summary_channel_id')
            channel_id = int(channel_id_str) if channel_id_str else None
            
            leaderboard_data['monthly_summary_channel_id'] = channel_id
            bot.data.save_guild_data(guild_id, "leaderboard_config", leaderboard_data)
            
            if channel_id:
                channel = guild.get_channel(channel_id)
                flash(f"Monatliche Zusammenfassung wird in #{channel.name} gepostet!", "success")
            else:
                flash("Monatliche Zusammenfassung deaktiviert.", "success")
            
        elif action == 'post_leaderboard':
            # Quick post leaderboard
            leaderboard_data = bot.data.get_guild_data(guild_id, "leaderboard_config")
            channel_id = leaderboard_data.get('leaderboard_channel_id')
            
            if not channel_id:
                flash("Bitte konfiguriere zuerst einen Leaderboard-Channel!", "danger")
                return redirect(url_for('manage_leaderboard_settings', guild_id=guild_id))
            
            channel = guild.get_channel(channel_id)
            if not channel:
                flash("Konfigurierter Channel nicht gefunden!", "danger")
                return redirect(url_for('manage_leaderboard_settings', guild_id=guild_id))
            
            leaderboard_type = request.form.get('leaderboard_type', 'messages')
            
            try:
                # Get leaderboard data
                import datetime
                now = datetime.datetime.now()
                current_month = now.strftime('%Y-%m')
                
                leaderboard = []
                title = ""
                description = "Alle Channels"

                if leaderboard_type == 'messages':
                    title = "🗨️ Meiste Nachrichten - Monatlich"
                    monthly_stats = bot.data.get_guild_data(guild_id, "monthly_stats")
                    month_data = monthly_stats.get(current_month, {})
                    
                    for user_id_str, user_data in month_data.items():
                        if not user_id_str.isdigit():
                            continue
                        member = guild.get_member(int(user_id_str))
                        if not member:
                            continue
                        
                        msg_count = user_data.get('total_messages', 0)
                        if msg_count > 0:
                            leaderboard.append({'member': member, 'value': msg_count})

                elif leaderboard_type == 'level':
                    title = "⭐ Höchstes Level - Allzeit"
                    users_data = bot.data.get_guild_data(guild_id, "level_users")
                    
                    for user_id_str, user_data in users_data.items():
                        if not user_id_str.isdigit():
                            continue
                        member = guild.get_member(int(user_id_str))
                        if not member:
                            continue
                        
                        leaderboard.append({
                            'member': member,
                            'value': user_data.get('level', 0),
                            'xp': user_data.get('xp', 0)
                        })

                elif leaderboard_type == 'streak_current':
                    title = "🔥 Längste aktive Streak"
                    guild_streaks = bot.data.get_guild_data(guild_id, "streaks")
                    
                    for user_id_str, data in guild_streaks.items():
                        if not user_id_str.isdigit():
                            continue
                        member = guild.get_member(int(user_id_str))
                        if not member:
                            continue
                        
                        current_streak = data.get('current_streak', 0)
                        if current_streak > 0:
                            leaderboard.append({'member': member, 'value': current_streak})

                elif leaderboard_type == 'streak_alltime':
                    title = "🏆 Längste Streak (Allzeit)"
                    guild_streaks = bot.data.get_guild_data(guild_id, "streaks")
                    
                    for user_id_str, data in guild_streaks.items():
                        if not user_id_str.isdigit():
                            continue
                        member = guild.get_member(int(user_id_str))
                        if not member:
                            continue
                        
                        max_streak = data.get('max_streak_ever', 0)
                        if max_streak > 0:
                            leaderboard.append({'member': member, 'value': max_streak})

                # Sort and limit
                leaderboard.sort(key=lambda x: x['value'], reverse=True)
                leaderboard = leaderboard[:20]

                if not leaderboard:
                    flash("Keine Daten für dieses Leaderboard verfügbar!", "warning")
                    return redirect(url_for('manage_leaderboard_settings', guild_id=guild_id))

                # Create embed
                import discord
                embed = discord.Embed(
                    title=title,
                    description=description,
                    color=discord.Color.blue(),
                    timestamp=datetime.datetime.now()
                )

                # Add leaderboard entries
                leaderboard_text = ""
                for idx, entry in enumerate(leaderboard, 1):
                    medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
                    
                    if leaderboard_type == 'messages':
                        leaderboard_text += f"{medal} **{entry['member'].display_name}** - {entry['value']:,} Nachrichten\n"
                    elif leaderboard_type == 'level':
                        leaderboard_text += f"{medal} **{entry['member'].display_name}** - Level {entry['value']} ({entry['xp']:,} XP)\n"
                    elif leaderboard_type == 'streak_current' or leaderboard_type == 'streak_alltime':
                        leaderboard_text += f"{medal} **{entry['member'].display_name}** - {entry['value']} Tage\n"

                embed.add_field(name="Rangliste", value=leaderboard_text or "Keine Einträge", inline=False)
                embed.set_footer(text=f"{guild.name} • {now.strftime('%d.%m.%Y %H:%M')}")

                # Send to channel
                async def send_embed():
                    await channel.send(embed=embed)

                future = asyncio.run_coroutine_threadsafe(send_embed(), bot.loop)
                future.result(timeout=10)

                flash(f"✅ Leaderboard wurde in #{channel.name} gepostet!", "success")

            except Exception as e:
                print(f"Error posting leaderboard: {e}")
                import traceback
                traceback.print_exc()
                flash(f"Fehler beim Posten: {str(e)}", "danger")
        
        return redirect(url_for('manage_leaderboard_settings', guild_id=guild_id))

    # GET request - show settings page
    leaderboard_data = bot.data.get_guild_data(guild_id, "leaderboard_config")
    
    return render_template('leaderboard_settings.html',
                         guild=guild,
                         settings=leaderboard_data,
                         admin_guilds=get_admin_guilds())


@app.route('/guild/<int:guild_id>/leaderboards', methods=['GET'])
@requires_authorization
def view_leaderboards(guild_id):
    """Zeigt die Leaderboards-Seite an."""
    if not check_guild_permissions(guild_id):
        flash("Du hast keine Berechtigung für diesen Server.", "danger")
        return redirect(url_for('dashboard'))

    guild = bot.get_guild(guild_id)
    if not guild:
        flash("Server nicht gefunden.", "danger")
        return redirect(url_for('dashboard'))

    # Get current month for display
    import datetime
    now = datetime.datetime.now()
    current_month = now.strftime('%B %Y')

    return render_template('leaderboards.html', 
                         guild=guild, 
                         current_month=current_month,
                         admin_guilds=get_admin_guilds())


@app.route('/guild/<int:guild_id>/leaderboards/data', methods=['GET'])
@requires_authorization
def get_leaderboards_data(guild_id):
    """API-Endpunkt zum Abrufen der Leaderboard-Daten."""
    if not check_guild_permissions(guild_id):
        return jsonify({"error": "Unauthorized"}), 403

    guild = bot.get_guild(guild_id)
    if not guild:
        return jsonify({"error": "Guild not found"}), 404

    # Get filter parameters
    channel_id = request.args.get('channel_id', type=int)
    leaderboard_type = request.args.get('type', 'messages')

    try:
        import datetime
        now = datetime.datetime.now()
        current_month = now.strftime('%Y-%m')
        
        leaderboard = []

        if leaderboard_type == 'messages':
            # Message count leaderboard (ALWAYS monthly)
            monthly_stats = bot.data.get_guild_data(guild_id, "monthly_stats")
            month_data = monthly_stats.get(current_month, {})
            
            for user_id_str, user_data in month_data.items():
                if not user_id_str.isdigit():
                    continue
                
                member = guild.get_member(int(user_id_str))
                if not member:
                    continue
                
                # Filter by channel if specified
                if channel_id:
                    msg_count = user_data.get('channels', {}).get(str(channel_id), 0)
                else:
                    msg_count = user_data.get('total_messages', 0)
                
                if msg_count > 0:
                    leaderboard.append({
                        'name': member.display_name,
                        'avatar_url': str(member.display_avatar.url),
                        'value': msg_count
                    })

        elif leaderboard_type == 'level':
            # Level leaderboard (ALWAYS all-time from level system)
            users_data = bot.data.get_guild_data(guild_id, "level_users")
            
            for user_id_str, user_data in users_data.items():
                if not user_id_str.isdigit():
                    continue
                
                member = guild.get_member(int(user_id_str))
                if not member:
                    continue
                
                leaderboard.append({
                    'name': member.display_name,
                    'avatar_url': str(member.display_avatar.url),
                    'level': user_data.get('level', 0),
                    'xp': user_data.get('xp', 0),
                    'value': user_data.get('level', 0)
                })

        elif leaderboard_type == 'streak_current':
            # Current active streak leaderboard
            guild_streaks = bot.data.get_guild_data(guild_id, "streaks")
            for user_id_str, data in guild_streaks.items():
                if not user_id_str.isdigit():
                    continue
                
                member = guild.get_member(int(user_id_str))
                if not member:
                    continue
                
                current_streak = data.get('current_streak', 0)
                if current_streak > 0:
                    leaderboard.append({
                        'name': member.display_name,
                        'avatar_url': str(member.display_avatar.url),
                        'value': current_streak
                    })

        elif leaderboard_type == 'streak_alltime':
            # All-time longest streak leaderboard (includes past streaks)
            guild_streaks = bot.data.get_guild_data(guild_id, "streaks")
            for user_id_str, data in guild_streaks.items():
                if not user_id_str.isdigit():
                    continue
                
                member = guild.get_member(int(user_id_str))
                if not member:
                    continue
                
                max_streak = data.get('max_streak_ever', 0)
                if max_streak > 0:
                    leaderboard.append({
                        'name': member.display_name,
                        'avatar_url': str(member.display_avatar.url),
                        'value': max_streak
                    })


        # Sort leaderboard by value (descending)
        leaderboard.sort(key=lambda x: x['value'], reverse=True)
        
        # Limit to top 50
        leaderboard = leaderboard[:50]

        return jsonify({
            'leaderboard': leaderboard,
            'total': len(leaderboard)
        })

    except Exception as e:
        print(f"Error generating leaderboard: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/guild/<int:guild_id>/leaderboards/post', methods=['POST'])
@requires_authorization
def post_leaderboard_to_channel(guild_id):
    """Postet ein Leaderboard in einen Discord-Channel."""
    if not check_guild_permissions(guild_id):
        return jsonify({"error": "Unauthorized"}), 403

    guild = bot.get_guild(guild_id)
    if not guild:
        return jsonify({"error": "Guild not found"}), 404

    try:
        data = request.get_json()
        channel_id = data.get('channel_id')
        leaderboard_type = data.get('type', 'messages')
        filter_channel_id = data.get('filter_channel_id')

        if not channel_id:
            return jsonify({"error": "Channel ID required"}), 400

        channel = guild.get_channel(channel_id)
        if not channel:
            return jsonify({"error": "Channel not found"}), 404

        # Get leaderboard data
        import datetime
        now = datetime.datetime.now()
        current_month = now.strftime('%Y-%m')
        
        leaderboard = []
        title = ""
        description = ""

        if leaderboard_type == 'messages':
            title = "🗨️ Meiste Nachrichten - Monatlich"
            monthly_stats = bot.data.get_guild_data(guild_id, "monthly_stats")
            month_data = monthly_stats.get(current_month, {})
            
            for user_id_str, user_data in month_data.items():
                if not user_id_str.isdigit():
                    continue
                member = guild.get_member(int(user_id_str))
                if not member:
                    continue
                
                if filter_channel_id:
                    msg_count = user_data.get('channels', {}).get(str(filter_channel_id), 0)
                else:
                    msg_count = user_data.get('total_messages', 0)
                
                if msg_count > 0:
                    leaderboard.append({
                        'member': member,
                        'value': msg_count
                    })
            
            if filter_channel_id:
                filter_ch = guild.get_channel(filter_channel_id)
                description = f"Nachrichten in #{filter_ch.name if filter_ch else 'unbekannt'}"
            else:
                description = "Alle Channels"

        elif leaderboard_type == 'level':
            title = "⭐ Höchstes Level - Allzeit"
            users_data = bot.data.get_guild_data(guild_id, "level_users")
            
            for user_id_str, user_data in users_data.items():
                if not user_id_str.isdigit():
                    continue
                member = guild.get_member(int(user_id_str))
                if not member:
                    continue
                
                leaderboard.append({
                    'member': member,
                    'value': user_data.get('level', 0),
                    'xp': user_data.get('xp', 0)
                })

        elif leaderboard_type == 'streak_current':
            title = "🔥 Längste aktive Streak"
            guild_streaks = bot.data.get_guild_data(guild_id, "streaks")
            
            for user_id_str, data in guild_streaks.items():
                if not user_id_str.isdigit():
                    continue
                member = guild.get_member(int(user_id_str))
                if not member:
                    continue
                
                current_streak = data.get('current_streak', 0)
                if current_streak > 0:
                    leaderboard.append({
                        'member': member,
                        'value': current_streak
                    })

        elif leaderboard_type == 'streak_alltime':
            title = "🏆 Längste Streak (Allzeit)"
            guild_streaks = bot.data.get_guild_data(guild_id, "streaks")
            
            for user_id_str, data in guild_streaks.items():
                if not user_id_str.isdigit():
                    continue
                member = guild.get_member(int(user_id_str))
                if not member:
                    continue
                
                max_streak = data.get('max_streak_ever', 0)
                if max_streak > 0:
                    leaderboard.append({
                        'member': member,
                        'value': max_streak
                    })

        # Sort and limit
        leaderboard.sort(key=lambda x: x['value'], reverse=True)
        leaderboard = leaderboard[:20]  # Top 20 for Discord message

        if not leaderboard:
            return jsonify({"error": "Keine Daten verfügbar"}), 400

        # Create embed
        import discord
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now()
        )

        # Add leaderboard entries
        leaderboard_text = ""
        for idx, entry in enumerate(leaderboard, 1):
            medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
            
            if leaderboard_type == 'messages':
                leaderboard_text += f"{medal} **{entry['member'].display_name}** - {entry['value']:,} Nachrichten\n"
            elif leaderboard_type == 'level':
                leaderboard_text += f"{medal} **{entry['member'].display_name}** - Level {entry['value']} ({entry['xp']:,} XP)\n"
            elif leaderboard_type == 'streak_current' or leaderboard_type == 'streak_alltime':
                leaderboard_text += f"{medal} **{entry['member'].display_name}** - {entry['value']} Tage\n"

        embed.add_field(name="Rangliste", value=leaderboard_text or "Keine Einträge", inline=False)
        embed.set_footer(text=f"{guild.name} • {now.strftime('%d.%m.%Y %H:%M')}")

        # Send to channel
        async def send_embed():
            await channel.send(embed=embed)

        future = asyncio.run_coroutine_threadsafe(send_embed(), bot.loop)
        future.result(timeout=10)

        return jsonify({"success": True})

    except Exception as e:
        print(f"Error posting leaderboard: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    pass  # Lock-Logik entfernt


    def run_flask():
        # Apply ProxyFix to handle Cloudflare headers correctly
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
        
        port = 5000
        print(f"Flask startet auf Port {port}...")
        try:
            app.run(port=port, host="0.0.0.0", debug=False, use_reloader=False)
        except Exception as e:
            print(f"⚠️ Webserver konnte nicht starten (evtl. Port belegt): {e}")

    # Webserver in eigenem Thread starten (Daemon=True damit er mit Bot endet)
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()

    # Bot starten
    # Bot starten
    import time
    from aiohttp import ClientConnectorError

    token = config.get("token")
    
    if not token:
        print("❌ Kein Token in der Konfiguration gefunden!")
    else:
        print(f"🚀 Starte Bot...")
        while True:
            try:
                bot.run(token)
                # Wenn bot.run() normal zurückkehrt (z.B. durch shutdown), Schleife beenden
                break
            except (ClientConnectorError, OSError) as e:
                print(f"\n⚠️ Netzwerkfehler beim Verbinden ({e}). Neuer Versuch in 10 Sekunden...")
                time.sleep(10)
            except Exception as e:
                print(f"\n❌ Kritischer Fehler: {e}")
                print("Neuer Versuch in 10 Sekunden...")
                time.sleep(10)
    
    print("Bot wurde beendet.")