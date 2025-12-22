import discord
from discord.ext import commands

class SettingsCog(commands.Cog, name="Einstellungen"):
    """Cog für alle befehle, die Servereinstellungen verändern."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="prefix", help="Ändert das Befehls-Präfix des Bots.")
    @commands.has_permissions(administrator=True)
    async def change_prefix(self, ctx, new_prefix: str):
        """Ändert das Präfix für diesen Server."""
        if len(new_prefix) > 5:
            await ctx.send("Das Präfix darf maximal 5 Zeichen lang sein.")
            return

        guild_config = self.bot.data.get_server_config(ctx.guild.id)
        guild_config['prefix'] = new_prefix
        self.bot.data.save_server_config(ctx.guild.id, guild_config)
        
        await ctx.send(f'Das Präfix wurde erfolgreich zu `{new_prefix}` geändert.')

    @commands.command(name="setwelcome", help="Legt den Willkommenskanal fest. Ohne Kanal wird die Funktion deaktiviert.")
    @commands.has_permissions(administrator=True)
    async def set_welcome_channel(self, ctx, channel: discord.TextChannel = None):
        """Legt einen Kanal für Willkommensnachrichten fest oder deaktiviert ihn."""
        guild_config = self.bot.data.get_server_config(ctx.guild.id)

        if channel:
            guild_config['welcome_channel_id'] = channel.id
            await ctx.send(f'Der Willkommenskanal wurde auf {channel.mention} gesetzt.')
        else:
            guild_config['welcome_channel_id'] = None
            await ctx.send('Willkommensnachrichten wurden für diesen Server deaktiviert.')
        
        self.bot.data.save_server_config(ctx.guild.id, guild_config)

    @change_prefix.error
    @set_welcome_channel.error
    async def on_settings_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("Du hast nicht die erforderlichen Berechtigungen, um diesen Befehl zu verwenden.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Ein benötigtes Argument fehlt. Benutze `!help`, um die korrekte Verwendung zu sehen.")
        else:
            await ctx.send("Ein unerwarteter Fehler ist aufgetreten.")
            print(error)


async def setup(bot):
    await bot.add_cog(SettingsCog(bot))
