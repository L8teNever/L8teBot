import json
import os
import shutil
from utils.config import GUILDS_DATA_DIR

class DataManager:
    def __init__(self):
        self._ensure_directory(GUILDS_DATA_DIR)
        # Cache could be implemented here if performance becomes an issue
        # self._cache = {}

    def _ensure_directory(self, path):
        if not os.path.exists(path):
            os.makedirs(path)

    def _get_guild_dir(self, guild_id):
        path = os.path.join(GUILDS_DATA_DIR, str(guild_id))
        self._ensure_directory(path)
        return path

    def _get_file_path(self, guild_id, filename):
        return os.path.join(self._get_guild_dir(guild_id), f"{filename}.json")

    def load_json(self, path, default=None):
        if default is None:
            default = {}
        if not os.path.exists(path):
            self.save_json(path, default)
            return default
        with open(path, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return default

    def save_json(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # --- Guild Specific Data Access ---

    def get_guild_data(self, guild_id, module_name, default=None):
        """
        Loads data for a specific module of a specific guild.
        Example: get_guild_data(12345, "level") -> loads data/guilds/12345/level.json
        """
        path = self._get_file_path(guild_id, module_name)
        return self.load_json(path, default)

    def save_guild_data(self, guild_id, module_name, data):
        """
        Saves data directly to the guild's module file.
        """
        path = self._get_file_path(guild_id, module_name)
        self.save_json(path, data)

    # --- Configuration Wrappers ---

    def get_server_config(self, guild_id):
        """Standard 'server_data' like prefixes etc."""
        return self.get_guild_data(guild_id, "config")

    def save_server_config(self, guild_id, data):
        self.save_guild_data(guild_id, "config", data)

    # --- Global Config ---
    def load_global_config(self, path):
        """
        Loads configuration from environment variables first, then falls back to config.json.
        """
        import os
        config = {}
        
        # Load from config.json if it exists
        if os.path.exists(path):
            config = self.load_json(path)
            
        # Keys to check in environment variables (case-insensitive)
        keys = [
            "token", "DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET", "DISCORD_REDIRECT_URI",
            "SECRET_KEY", "WEB_BASE_URL", "TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET",
            "TWITCH_BOT_USERNAME", "TWITCH_BOT_TOKEN", "TWITCH_REDIRECT_URI", "ADMIN_TWITCH_NAMES"
        ]
        
        for key in keys:
            env_val = os.environ.get(key)
            if env_val:
                env_val = env_val.strip("'\"")
                config[key] = env_val
            else:
                if key not in config or not config[key]:
                    if key in ["token", "DISCORD_CLIENT_ID", "TWITCH_CLIENT_ID"]:
                        print(f"  [!] Kritische Info fehlt: {key}")
                
        return config

