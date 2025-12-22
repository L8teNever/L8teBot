#!/bin/bash
# L8teBot Backup Restore Script
# Usage: ./restore_backup.sh /path/to/backup.zip

if [ -z "$1" ]; then
    echo "❌ Fehler: Keine Backup-Datei angegeben"
    echo "Usage: ./restore_backup.sh /path/to/backup.zip"
    exit 1
fi

BACKUP_FILE="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$SCRIPT_DIR/data"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "❌ Backup-Datei nicht gefunden: $BACKUP_FILE"
    exit 1
fi

echo "🔄 Stoppe Container..."
docker-compose down

echo "📦 Erstelle Sicherung der aktuellen Daten..."
if [ -d "$DATA_DIR" ]; then
    mv "$DATA_DIR" "${DATA_DIR}_backup_$(date +%Y%m%d_%H%M%S)"
fi

echo "📂 Erstelle neues data Verzeichnis..."
mkdir -p "$DATA_DIR"

echo "📥 Entpacke Backup..."
unzip -q "$BACKUP_FILE" -d /tmp/l8tebot_restore

# Prüfe ob 'data' Ordner im Backup existiert
if [ -d "/tmp/l8tebot_restore/data" ]; then
    echo "✅ Backup enthält 'data' Ordner - kopiere Inhalt..."
    cp -r /tmp/l8tebot_restore/data/* "$DATA_DIR/"
else
    echo "✅ Backup ist direkt der Inhalt - kopiere alles..."
    cp -r /tmp/l8tebot_restore/* "$DATA_DIR/"
fi

echo "🧹 Räume auf..."
rm -rf /tmp/l8tebot_restore

echo "🚀 Starte Container neu..."
docker-compose up -d

echo "✅ Backup erfolgreich wiederhergestellt!"
echo "📊 Überprüfe die Logs mit: docker-compose logs -f"
