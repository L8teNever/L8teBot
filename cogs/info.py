# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands, Embed, Color
from datetime import datetime

class InfoCog(commands.Cog, name="Information"):
    """Allgemeine Informationen und Datenschutz"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="botinfo", description="Zeigt detaillierte Infos zum Bot und zum Datenschutz an")
    async def info_command(self, interaction: discord.Interaction):
        """Sendet einen ausführlichen Datenschutz- und Info-Embed (Privat)"""
        
        embed = Embed(
            title="ℹ️ Information & Datenschutz - L8teBot",
            description=(
                "Dieser Bot wurde entwickelt, um die Aktivität und den Zusammenhalt auf diesem Server zu fördern. "
                "Hier erfährst du, wie der Bot funktioniert und wie wir mit deinen Daten umgehen."
            ),
            color=Color.blue(),
            timestamp=datetime.utcnow()
        )

        embed.add_field(
            name="🚀 Hauptfunktionen",
            value=(
                "• **Level-System:** Sammle XP durch Nachrichten und steige im Level auf.\n"
                "• **Streaks (Flammen):** Bleibe täglich aktiv, um deine Streak zu halten.\n"
                "• **Leaderboards:** Messe dich mit anderen in monatlichen Statistiken.\n"
                "• **LFG (Mitspieler-Suche):** Erstelle oder tritt Gruppen für deine Lieblingsspiele bei."
            ),
            inline=False
        )

        embed.add_field(
            name="📊 Welche Daten werden gesammelt?",
            value=(
                "Der Bot speichert lediglich technische Daten, die für die Funktionen zwingend notwendig sind:\n"
                "• **IDs:** Deine Discord User-ID (um XP/Levels deinem Account zuzuordnen).\n"
                "• **Statistiken:** Anzahl der gesendeten Nachrichten (pro Monat & Gesamt).\n"
                "• **Zeitstempel:** Zeitpunkt deiner letzten Nachricht (für das Streak-System).\n"
                "• **LFG-Daten:** Temporäre Speicherung deiner Gruppenteilnahmen."
            ),
            inline=False
        )

        embed.add_field(
            name="🛡️ Deine Privatsphäre",
            value=(
                "Deine Privatsphäre ist uns extrem wichtig. Daher gilt:\n"
                "• ❌ **Keine Inhalts-Speicherung:** Wir speichern NIEMALS, *was* du schreibst. Nur *dass* du geschrieben hast.\n"
                "• ❌ **Keine Personenbezogenen Daten:** Wir sammeln keine Namen, E-Mails, IPs oder andere private Infos.\n"
                "• ❌ **Keine Weitergabe:** Deine Daten werden nicht verkauft oder an Dritte weitergegeben.\n"
                "• ✅ **Lokal & Sicher:** Alle Daten werden verschlüsselt auf unserem eigenen System gespeichert."
            ),
            inline=False
        )

        embed.add_field(
            name="⚙️ Verwaltung",
            value=(
                "Admins können über das Web-Dashboard jederzeit Module deaktivieren oder Daten zurücksetzen. "
                "Bei Fragen zum Datenschutz wende dich bitte an das Server-Team."
            ),
            inline=False
        )

        embed.set_footer(text="L8teBot - Dein Community Begleiter", icon_url=self.bot.user.display_avatar.url)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(InfoCog(bot))
