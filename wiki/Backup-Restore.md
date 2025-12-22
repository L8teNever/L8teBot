# Backup & Restore mit Docker

## ⚠️ Wichtig für Docker-Nutzer

Das Backup-System über die Website funktioniert **nicht korrekt** mit Docker Volumes, da beim Container-Neustart die Daten vom Host-System wieder gemountet werden.

## Backup erstellen

### Über die Website
1. Gehe zu **Admin** → **Maintenance**
2. Klicke auf **Backup herunterladen**
3. Speichere die `.zip` Datei

### Manuell (auf dem Server)
```bash
cd /pfad/zu/deinem/bot
zip -r backup.zip data/
```

## Backup wiederherstellen

### ✅ Empfohlene Methode (Script)

**Linux/Mac:**
```bash
# Lade das Backup auf deinen Server hoch
# Dann führe aus:
chmod +x restore_backup.sh
./restore_backup.sh /pfad/zum/backup.zip
```

**Windows (PowerShell):**
```powershell
.\restore_backup.ps1 "C:\pfad\zum\backup.zip"
```

Das Script:
1. Stoppt den Container
2. Sichert die aktuellen Daten
3. Entpackt das Backup
4. Startet den Container neu

### ❌ NICHT empfohlen: Über die Website
Die Website-Funktion funktioniert nicht mit Docker Volumes, da die Daten beim Neustart überschrieben werden.

## Manuelle Wiederherstellung

Falls die Scripts nicht funktionieren:

```bash
# 1. Container stoppen
docker-compose down

# 2. Backup entpacken
unzip backup.zip -d /tmp/restore

# 3. Daten kopieren
# Wenn das Backup einen 'data' Ordner enthält:
cp -r /tmp/restore/data/* ./data/

# Wenn das Backup direkt die Dateien enthält:
cp -r /tmp/restore/* ./data/

# 4. Container starten
docker-compose up -d
```
