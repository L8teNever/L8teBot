from discord.ext import commands
import discord

class UtilityCog(commands.Cog, name="Nützliches"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="ping", help="Zeigt die Latenz des Bots an.")
    async def ping(self, ctx):
        """Prüft die Latenz des Bots."""
        latency = round(self.bot.latency * 1000)
        await ctx.send(f'Pong! 🏓 Latenz: {latency}ms')
        
    @commands.command(name="help", help="Zeigt einen Link zur Online-Hilfe an.")
    async def custom_help(self, ctx):
        """Sendet einen Link zur Webseite mit der Befehlsübersicht."""
        embed = discord.Embed(
            title="Hilfe & Befehlsübersicht",
            description="Eine vollständige Übersicht aller Befehle und Anleitungen findest du auf unserer Webseite:\n\n**[Hier klicken, um zur Hilfe zu gelangen](https://l8tenever.de/#wiki)**",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(UtilityCog(bot))