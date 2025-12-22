# 📚 L8teBot Dokumentation

Willkommen in der Dokumentation für den **L8teBot**!
Dieser Bot bietet eine Vielzahl von Funktionen für die Verwaltung und Interaktion auf deinem Discord-Server.

Inhaltsverzeichnis:
- [Module & Funktionen](#module--funktionen)
- [Befehlsübersicht](#befehlsübersicht)
- [Web-Dashboard](#web-dashboard)

## Module & Funktionen

Der Bot ist modular aufgebaut. Jedes Modul kann über das Web-Dashboard aktiviert oder deaktiviert werden.

### 🎂 Geburtstage
Verwaltet die Geburtstage der Community.
- **Funktion**: Automatische Glückwünsche und temporäre Rollenvergabe.
- **Interaktion**: 
  - Die Verwaltung (Hinzufügen/Löschen) läuft über Buttons in einem festgelegten Kanal.
  - Es gibt **keine** Chat-Befehle hierfür.

### 🧮 Zählen (Counting)
Ein Minispiel, bei dem die Community endlos zählen muss.
- **Funktion**: 
  - Der Bot überwacht einen Kanal. Zahlen müssen in der richtigen Reihenfolge gepostet werden.
  - User können nicht zweimal hintereinander zählen.
  - Bei falschen Zahlen wird die Nachricht gelöscht oder resettet (je nach Config).
  - Meilensteine lösen spezielle Nachrichten aus.
- **Interaktion**:
  - Einfach Zahlen in den Kanal schreiben.

### 📈 Level-System
Belohnt Aktivität mit Erfahrungspunkten (XP).
- **Funktion**:
  - XP für Nachrichten (mit Cooldown).
  - Tägliche XP-Belohnung.
  - Rollenaufstieg bei bestimmten Leveln.
  - XP-Boosts durch bestimmte Rollen.
- **Befehle**:
  - `/rank [user]`: Zeigt deinen Rang oder den eines anderen Nutzers an.
  - `/leaderboard`: Zeigt die Top 10 Rangliste.

### 🎟️ Ticket-System
Privater Support für deine User.
- **Funktion**:
  - User können per Knopfdruck private Ticket-Kanäle erstellen.
  - Kategorisierung der Anliegen (z.B. Support, Bewerbung).
  - Admins erhalten einen separaten Kontroll-Thread ("Konsole").
  - Transkripte werden bei Schließung erstellt.
- **Interaktion**:
  - Alles über Buttons und Menüs im Ticket-Panel.
  - **Keine** Chat-Befehle notwendig.

### 🛡️ Moderation & Sicherheit
Automatisierte und manuelle Moderation.
- **Befehle**:
  - `/kick <member> [grund]`: Kickt ein Mitglied.
  - `/ban <member> [grund]`: Bannt ein Mitglied.
- **Weitere Module**:
  - **Global Ban**: Gleicht Bans mit einer globalen Datenbank ab (falls aktiviert).
  - **Guard / Gatekeeper**: Schutzfunktionen gegen Raids oder unerwünschte User (konfigurierbar).

### 📺 Twitch Integration
Verbindet deinen Server mit Twitch.
- **Live-Alerts**: Benachrichtigt, wenn ein Streamer live geht.
- **Clips**: Postet automatisch neue Clips von überwachten Kanälen.

### 🔊 Temp-Channels
Dynamische Sprachkanäle ("Join to Create").
- **Funktion**: Erstellt temporäre Voice-Channel, wenn ein User den Hub-Kanal betritt, und löscht sie, wenn sie leer sind.
- **Einstellung**: Kanalnamen und Limits sind konfigurierbar.

### 🛠️ Nützliches (Utility)
Allgemeine Helferlein.
- **Befehle**:
  - `!ping`: Zeigt die aktuelle Reaktionszeit des Bots.
  - `!help`: Verweist auf diese Dokumentation/Webseite.

---

## Befehlsübersicht

Hier ist eine schnelle Liste aller verfügbaren Befehle.

| Befehl | Typ | Beschreibung |
| :--- | :---: | :--- |
| **`!ping`** | Prefix | Zeigt die Latenz (Ping) an. |
| **`!help`** | Prefix | Zeigt den Hilfe-Link. |
| **`/rank`** | Slash | Zeigt Level und XP eines Users. |
| **`/leaderboard`** | Slash | Zeigt die XP-Bestenliste. |
| **`/kick`** | Slash | Kickt ein Mitglied. |
| **`/ban`** | Slash | Bannt ein Mitglied. |

> **Hinweis**: Viele Funktionen des Bots (Tickets, Geburtstage, etc.) benötigen keine Befehle, sondern funktionieren über Buttons und Menüs direkt im Discord.

---

## Web-Dashboard

Das Herzstück der Konfiguration ist das Web-Dashboard.
Logge dich dort ein, um:
- Module an/auszuschalten.
- Kanäle für Features festzulegen (z.B. Willkommens-Kanal, Zähl-Kanal).
- Rollen und Nachrichten zu konfigurieren.
- Tickets und Rechte zu verwalten.

Alle Einstellungen werden sofort live übernommen.
