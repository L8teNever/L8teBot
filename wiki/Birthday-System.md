# 🎂 Geburtstags-System

Verpasse nie wieder einen Geburtstag! Der Bot gratuliert deinen Mitgliedern automatisch an ihrem Ehrentag und kann sogar eine spezielle Rolle vergeben.

## 📝 Features
*   **Datum speichern:** User können ihren Geburtstag selbst hinterlegen.
*   **Automatische Glückwünsche:** Jeden Morgen prüft der Bot, wer Geburtstag hat, und postet eine Nachricht im konfigurierten Kanal.
*   **Geburtstags-Rolle:** Du kannst eine Rolle definieren (z.B. "Geburtstagskind"), die der User für genau 24 Stunden erhält.
*   **Datenschutz:** User können ihr Alter verbergen, wenn sie nur den Tag und Monat feiern möchten.

---

## ⚙️ Setup
1.  Aktiviere das Modul im Dashboard.
2.  Wähle den **Glückwunsch-Kanal** aus.
3.  Definiere einen **Text**, den der Bot posten soll (nutze Platzhalter wie `{user}`).
4.  Wähle optional eine **Geburtstags-Rolle**.

---

## ⌨️ Befehle
*   `!birthday set <Tag> <Monat> [Jahr]` - Speichere deinen Geburtstag.
*   `!birthday list` - Zeigt die nächsten anstehenden Geburtstage auf dem Server.
*   `!birthday remove` - Löscht dein eingetragenes Datum.

---

## 💡 Automatischer Cleanup
Wenn ein User den Server verlässt, wird sein Geburtstag automatisch aus der Datenbank gelöscht, um deine Daten aktuell und sauber zu halten.
