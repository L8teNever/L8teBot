# 📈 Level-System

Belohne die Aktivität deiner Mitglieder mit einem dynamischen Level-System. User sammeln Erfahrungspunkte (XP) durch das Schreiben von Nachrichten und können so im Level aufsteigen.

## 📝 Funktionsweise
*   **XP pro Nachricht:** User erhalten pro Nachricht XP (standardmäßig zwischen 15 und 25 XP).
*   **Cooldown:** Um Spam zu vermeiden, gibt es einen Cooldown (meist 1 Minute), in dem keine doppelten XP gesammelt werden können.
*   **Leaderboard:** Ein globales Leaderboard zeigt die aktivsten User deines Servers.
*   **Level-Up Nachrichten:** Der Bot gratuliert Usern automatisch beim Erreichen eines neuen Levels.

---

## ⚙️ Konfiguration
Im Dashboard kannst du das Level-System feinjustieren:
*   **Status:** Schalte das System ein oder aus.
*   **Level-Up Kanal:** Wähle aus, ob die Glückwünsche im aktuellen Kanal, in einem festen Kanal oder gar nicht gesendet werden sollen.
*   **Rollen-Belohnungen:** (Optional) Du kannst festlegen, dass User beim Erreichen bestimmter Level automatisch Discord-Rollen erhalten.

---

## ⌨️ Befehle
*   `!rank` (oder `/rank`) - Zeigt deine aktuelle Karte mit XP, Level und Rang an.
*   `!leaderboard` (oder `/leaderboard`) - Zeigt die Top 10 User des Servers.

---

## 🛠️ Daten-Migration
Solltest du von einem anderen Bot kommen, bietet der L8teBot Tools zum Importieren von Level-Daten, sofern diese in einem kompatiblen Format vorliegen.
