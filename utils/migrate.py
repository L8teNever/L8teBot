import os
import json
from utils.config import *
from utils.data_manager import DataManager

def process_migration_data(module_name, data, save_callback=None):
    """
    Verarbeitet rohe JSON-Daten und migriert sie in die neue Struktur.
    save_callback: Eine Funktion (guild_id, module_name, data) -> void, um die Daten zu speichern.
                   Wenn None, wird DataManager direkt verwendet.
    """
    if save_callback is None:
        dm = DataManager()
        save_callback = dm.save_guild_data

    migrated_count = 0
    # Iterate through top-level keys (Guild IDs)
    if isinstance(data, dict):
        for guild_id_str, guild_data in data.items():
            # Basic check if key is a guild ID (numeric)
            if guild_id_str.isdigit():
                # Fix potential integer keys for users in level data and streaks
                if module_name in ["level_users", "streaks"]:
                   guild_data = {str(k): v for k, v in guild_data.items()}
                
                save_callback(guild_id_str, module_name, guild_data)
                migrated_count += 1
            # Special cases for non-guild keys (like 'default' milestones) could be handled here
    
    return migrated_count

def migrate():
    print("Starte Migration der Daten in die neue Ordnerstruktur...")
    
    # Map existing files to new module names
    # (Old Path, New Module Name)
    MAPPING = [
        (OLD_DATA_PATH, "config"),
        (OLD_BIRTHDAY_DATA_PATH, "birthday"),
        (OLD_COUNTING_DATA_PATH, "counting"),
        (OLD_MILESTONES_DATA_PATH, "milestones"),
        (OLD_LEVEL_DATA_PATH, "level_config"),
        (OLD_LEVEL_USER_DATA_PATH, "level_users"),
        (OLD_STREAMERS_DATA_PATH, "streamers"),
        (OLD_TICKET_CONFIG_PATH, "ticket_config"),
        (OLD_TICKETS_DATA_PATH, "tickets"),
        (OLD_TEMP_CHANNEL_DATA_PATH, "temp_channels"),
        (OLD_TWITCH_CLIPS_DATA_PATH, "twitch_clips"),
        (OLD_TWITCH_ALERT_DATA_PATH, "twitch_alerts"),
        (OLD_STREAK_DATA_PATH, "streaks"),
        (OLD_GATEKEEPER_DATA_PATH, "gatekeeper"),
        (OLD_GUARD_DATA_PATH, "guard"),
        (OLD_GLOBAL_BAN_DATA_PATH, "global_ban"),
    ]

    for old_path, module_name in MAPPING:
        if os.path.exists(old_path):
            print(f"Verarbeite {os.path.basename(old_path)} -> {module_name}.json ...")
            try:
                with open(old_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                process_migration_data(module_name, data)
                
                # Rename old file to .bak to avoid confusion
                os.rename(old_path, old_path + ".bak")
                print(f"✅ {os.path.basename(old_path)} migriert und in .bak umbenannt.")

            except Exception as e:
                print(f"❌ Fehler bei {old_path}: {e}")
        else:
            print(f"ℹ️ {os.path.basename(old_path)} nicht gefunden, überspringe.")

    print("Migration abgeschlossen.")

if __name__ == "__main__":
    migrate()
