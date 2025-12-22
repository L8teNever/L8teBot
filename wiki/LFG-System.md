# 🎮 LFG System (Mitspieler-Suche)

Das LFG-Modul (Looking For Group) automatisiert die Suche nach Mitspielern auf deinem Discord-Server. Es bietet einen zentralen Anlaufpunkt für User, um Suchen zu erstellen, und organisiert die Kommunikation in temporären, privaten Kanälen.

## 📝 Funktionen im Überblick
*   **Opt-In System:** User müssen eine bestimmte Rolle haben, um das System zu nutzen (schont die Nerven derer, die nicht zocken).
*   **Privater Lobby-Kanal:** Alle aktiven Suchen werden in einem zentralen Kanal gepostet, der nur für Teilnehmer sichtbar ist.
*   **Automatische Gruppen-Threads:** Für jede Suche wird ein eigener privater Thread erstellt, in dem sich die Teilnehmer absprechen können.
*   **Temporäre Rollen:** Teilnehmer erhalten eine temporäre Rolle für die Dauer der Suche, um sie einfach erwähnen zu können.
*   **Automatisches Cleanup:** Sobald eine Suche beendet wird, löscht der Bot die Rolle, archiviert den Thread und entfernt die Nachricht aus der Lobby.

---

## ⚙️ Setup & Konfiguration

### 1. Teilnehmer-Rolle erstellen
Erstelle eine Rolle (z.B. "Gamers" oder "LFG"), die deine User sich selbst geben können (z.B. über ein Reaction-Role System). Nur User mit dieser Rolle haben Zugriff auf das LFG-System.

### 2. Kanäle vorbereiten
Du benötigst zwei Kanäle:
1.  **Start-Kanal:** Hier postet der Bot die Nachricht mit dem Button "Spieler suchen". Dieser Kanal sollte für alle (oder alle Gamer) lesbar sein.
2.  **Lobby-Kanal:** Dies ist der Ort, an dem die Embeds der aktiven Suchen landen. Der Bot stellt diesen Kanal automatisch auf **Privat**, sodass nur Leute mit der Teilnehmer-Rolle ihn sehen können.

### 3. Dashboard-Einstellungen
Gehe im Web-Dashboard auf den Tab **LFG System** und konfiguriere:
*   **Teilnehmer-Rolle:** Wähle die oben erstellte Rolle aus.
*   **Start-Kanal:** Wähle den Kanal für den Button.
*   **Lobby-Kanal:** Wähle den Kanal für die Suchen.
*   **Max. Suchen:** Lege fest, wie viele Suchen ein User gleichzeitig offen haben darf (Standard: 3).

---

## 🚀 Nutzung für User

### Eine Suche starten
1.  Klicke im Start-Kanal auf den Button **"🎮 Spieler suchen"**.
2.  Fülle das Formular aus:
    *   **Spiel:** Was möchtest du zocken?
    *   **Beschreibung:** (Optional) Map, Skill-Level, etc.
    *   **Team-Größe:** Wie viele Leute suchst du?
    *   **Dauer:** Wie lange planst du zu spielen?
3.  Der Bot postet nun ein Embed in den **Lobby-Kanal**.

### Einer Suche beitreten
1.  Gehe in den **Lobby-Kanal**.
2.  Suche dir ein offenes Spiel aus und klicke auf **"Beitreten"**.
3.  Du wirst automatisch zum privaten Thread der Gruppe hinzugefügt und erhältst die Gruppen-Rolle.

### Suche beenden
Der Ersteller der Suche kann jederzeit im Lobby-Kanal oder im privaten Thread auf **"Suche beenden"** klicken. Der Bot räumt dann automatisch alles auf.

---

## 💡 Tipps für Admins
*   **Pins:** Die Start-Nachricht wird vom Bot automatisch gepinnt, damit sie immer oben im Kanal zu finden ist.
*   **Systemnachrichten:** Der Bot löscht automatisch "XYZ wurde zum Thread hinzugefügt" Nachrichten im Lobby-Kanal, um den Chat sauber zu halten.
*   **Berechtigungen:** Du musst dem Bot "Berechtigungen verwalten" im Lobby-Kanal geben, damit er ihn automatisch für Nicht-Teilnehmer sperren kann.
