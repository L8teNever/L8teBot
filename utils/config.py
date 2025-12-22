import os

# Hauptverzeichnis des Bots
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Fester Ordnername für Produktionsdaten
DATA_DIR_NAME = "data"

# Pfade
DATA_DIR = os.path.join(BASE_DIR, DATA_DIR_NAME)
GUILDS_DATA_DIR = os.path.join(DATA_DIR, "guilds")
BOT_CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

# Sicherstellen, dass Verzeichnisse existieren
os.makedirs(GUILDS_DATA_DIR, exist_ok=True)
