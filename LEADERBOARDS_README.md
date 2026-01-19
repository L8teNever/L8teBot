# Leaderboards Feature

## Übersicht

Das neue Leaderboards-Feature bietet umfassende Ranglisten für deinen Discord-Server mit automatischer Nachrichtenposting-Funktion.

### Features

1. **Vier Leaderboard-Typen (mit festen Zeiträumen):**
   - 🗨️ **Meiste Nachrichten** - **Immer monatlich** (nur aktueller Monat)
   - ⭐ **Höchstes Level** - **Immer Allzeit** (aus dem Level-System)
   - 🔥 **Längste aktive Streak** - **Aktuell** (nur aktive Streaks)
   - 🏆 **Längste Streak (Allzeit)** - **Allzeit** (auch vergangene Streaks)

2. **Flexible Filterung:**
   - **Channel-Filter**: Zeige Statistiken für einen bestimmten Channel oder alle Channels
   - **Automatisches Posten**: Sende Leaderboards direkt in einen Discord-Channel

3. **Live-Updates:**
   - Die Leaderboards aktualisieren sich dynamisch beim Wechsel der Filter
   - Keine Seitenneuladen erforderlich

4. **Unabhängiges Tracking:**
   - Das monatliche Nachrichten-Tracking läuft **unabhängig** vom Level-System
   - Beeinflusst **nicht** das bestehende XP/Level-System
   - Separate Datenbank für monatliche Statistiken

## Verwendung

### Web-Interface

1. Navigiere zu deinem Server-Dashboard
2. Klicke auf "Leaderboards" in den Schnellzugriffen
3. Wähle deine gewünschten Filter:
   - **Channel-Filter**: Bestimmter Channel oder "Alle Channels"
   - **Leaderboard-Typ**: Nachrichten/Level/Aktive Streak/Allzeit Streak
4. Die Rangliste wird automatisch aktualisiert

### Leaderboard in Channel posten

1. Wähle deine Filter wie gewünscht
2. Wähle im Dropdown "In Channel posten" den Ziel-Channel aus
3. Klicke auf "📤 Leaderboard in Channel posten"
4. Der Bot postet ein schönes Embed mit den Top 20 Einträgen

## Technische Details

### Zeiträume pro Typ

- **Nachrichten**: Immer nur der **aktuelle Monat** (z.B. Januar 2026)
  - Daten kommen aus dem `monthly_stats` Cog
  - Wird bei jeder Nachricht aktualisiert
  
- **Level**: Immer **Allzeit**-Statistiken
  - Daten kommen direkt aus dem `level_users` System
  - Zeigt die aktuellen Level und XP
  
- **Aktive Streak**: Nur **aktuelle** Streaks
  - Daten kommen aus dem `streaks` System (`current_streak`)
  - Zeigt nur Benutzer mit aktiven Streaks (>0 Tage)
  
- **Allzeit Streak**: **Längste jemals** erreichte Streaks
  - Daten kommen aus dem `streaks` System (`max_streak_ever`)
  - Zeigt auch Streaks, die bereits vorbei sind
  - Wird automatisch aktualisiert, wenn eine neue Rekord-Streak erreicht wird

### Streak-Tracking

Das Streak-System trackt jetzt **zwei Werte**:
- `current_streak`: Die aktuelle, laufende Streak
- `max_streak_ever`: Die längste jemals erreichte Streak (wird nie zurückgesetzt)

Wenn ein Benutzer seine bisherige Rekord-Streak übertrifft, wird `max_streak_ever` automatisch aktualisiert.

### Neue Dateien

1. **`cogs/monthly_stats.py`**: 
   - Neuer Cog für monatliches Tracking
   - Trackt Nachrichten pro Channel und Monat
   - Automatische Bereinigung von Daten älter als 12 Monate

2. **`web/templates/leaderboards.html`**:
   - Neue Leaderboard-Seite mit dynamischer Filterung
   - Responsive Design
   - Live-Datenaktualisierung via AJAX
   - Channel-Posting-Funktion

### Geänderte Dateien

1. **`cogs/streak.py`**:
   - Hinzugefügt: `max_streak_ever` Tracking
   - Automatische Aktualisierung bei neuen Rekorden

### Neue Routen

- **`/guild/<guild_id>/leaderboards`**: Hauptseite für Leaderboards (GET)
- **`/guild/<guild_id>/leaderboards/data`**: API-Endpunkt für dynamische Daten (GET)
- **`/guild/<guild_id>/leaderboards/post`**: API-Endpunkt zum Posten in Channels (POST)

### Datenstruktur

**Monatliche Statistiken** (`monthly_stats`):
```json
{
  "2026-01": {
    "123456789": {
      "total_messages": 150,
      "channels": {
        "987654321": 100,
        "876543210": 50
      }
    }
  }
}
```

**Streak-Daten** (`streaks`):
```json
{
  "123456789": {
    "current_streak": 10,
    "max_streak_ever": 25,
    "last_message_date": "2026-01-19"
  }
}
```

## Discord-Embed Format

Wenn ein Leaderboard gepostet wird, enthält es:
- **Titel**: Typ (z.B. "� Längste aktive Streak" oder "🏆 Längste Streak (Allzeit)")
- **Beschreibung**: Filter-Info (z.B. "Alle Channels" oder "Nachrichten in #general")
- **Rangliste**: Top 20 Einträge mit Medaillen (🥇🥈🥉)
- **Footer**: Server-Name und Zeitstempel

## Wichtige Hinweise

- **Monatliche Nachrichten** beeinflussen **nicht** das XP-System
- **Level-Daten** kommen direkt aus dem Level-System
- **Streak-Daten** kommen direkt aus dem Streak-System
- **Allzeit-Streaks** zeigen auch vergangene Rekorde
- Alte monatliche Daten (>12 Monate) werden automatisch gelöscht
- **Top 50** Einträge werden im Web-Interface angezeigt
- **Top 20** Einträge werden in Discord-Channels gepostet
- Die ersten 3 Plätze erhalten spezielle Medaillen (🥇🥈🥉)

## Unterschied zwischen den Streak-Leaderboards

### 🔥 Längste aktive Streak
- Zeigt nur **aktuelle, laufende** Streaks
- Wenn ein Benutzer seine Streak verliert, verschwindet er aus dieser Liste
- Perfekt um zu sehen, wer **gerade aktiv** ist

### 🏆 Längste Streak (Allzeit)
- Zeigt die **längsten jemals erreichten** Streaks
- Auch wenn die Streak vorbei ist, bleibt der Rekord bestehen
- Perfekt für **Hall of Fame** / Rekord-Anzeigen
- Wird nur aktualisiert, wenn jemand seinen eigenen Rekord übertrifft
