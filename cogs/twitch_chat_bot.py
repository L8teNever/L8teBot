# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import twitchio
from twitchio.ext import commands as t_commands
import asyncio
import os
import json
from typing import List, Optional

class TwitchChatBot(t_commands.Bot):
    def __init__(self, token, prefix, initial_channels, discord_cog, client_id, client_secret, bot_id):
        super().__init__(
            token=token, 
            prefix=prefix, 
            initial_channels=initial_channels,
            client_id=client_id,
            client_secret=client_secret,
            bot_id=bot_id
        )
        self.discord_cog = discord_cog

    async def event_ready(self):
        print(f'[Twitch IRC] Bot eingeloggt als | {self.nick}')
        print(f'[Twitch IRC] Verbunden mit {len(self.connected_channels)} Kanälen: {list(self.connected_channels)}')

    async def event_message(self, message):
        if message.echo:
            return

        print(f"[Twitch IRC] Nachricht von {message.author.name} in {message.channel.name}: {message.content}")

        # Handle built-in commands
        await self.handle_commands(message)

        # Handle custom commands
        if message.content.startswith('!'):
            parts = message.content[1:].split(' ')
            cmd_name = parts[0].lower()
            
            # Load config to check for custom command
            config = self.discord_cog.bot.data.load_json(self.discord_cog.config_path, {"channels": {}})
            channel_name = message.channel.name.lower()
            
            print(f"[Twitch IRC] Suche Befehl !{cmd_name} für Kanal {channel_name}")
            
            chan_config = config.get("channels", {}).get(channel_name, {})
            custom_cmds = chan_config.get("custom_commands", {})
            
            if cmd_name in custom_cmds:
                cmd_data = custom_cmds[cmd_name]
                print(f"[Twitch IRC] Befehl gefunden: {cmd_data}")
                
                # Check if it's the old format (just a string) or new format (dict)
                if isinstance(cmd_data, str):
                    await message.channel.send(cmd_data)
                    return

                response = cmd_data.get("response")
                permission = cmd_data.get("permission", "everyone")
                
                # Permission Check
                is_mod = message.author.is_mod or message.author.name.lower() == channel_name
                # Note: badges are a dict of strings in twitchio
                badges = message.author.badges if message.author.badges else {}
                is_vip = 'vip' in badges
                
                print(f"[Twitch IRC] User: {message.author.name}, Mod: {is_mod}, VIP: {is_vip}, Perm: {permission}")
                
                allowed = False
                if permission == "everyone":
                    allowed = True
                elif permission == "mods" and is_mod:
                    allowed = True
                elif permission == "vips" and (is_vip or is_mod):
                    allowed = True
                elif permission == "mods_vips" and (is_mod or is_vip):
                    allowed = True
                
                if allowed:
                    await message.channel.send(response)
                else:
                    print(f"[Twitch IRC] Zugriff verweigert für !{cmd_name}")

    @t_commands.command(name='l8te')
    async def l8te_command(self, ctx):
        await ctx.send(f'Hallo {ctx.author.name}! Ich bin der L8teBot Twitch-Moderator. 🚀')

class TwitchChatBotCog(commands.Cog, name="Twitch-Bot"):
    """Cog für den Twitch IRC Chat Bot."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.twitch_bot: Optional[TwitchChatBot] = None
        from utils.config import DATA_DIR
        self.config_path = os.path.join(DATA_DIR, "twitch_bot.json")
        self.bot.loop.create_task(self.initialize_twitch_bot())

    async def initialize_twitch_bot(self):
        """Initialisiert den Twitch Bot IRC Client."""
        await self.bot.wait_until_ready()
        
        token = self.bot.config.get("TWITCH_BOT_TOKEN")
        username = self.bot.config.get("TWITCH_BOT_USERNAME")
        client_id = self.bot.config.get("TWITCH_CLIENT_ID")
        client_secret = self.bot.config.get("TWITCH_CLIENT_SECRET")
        
        if not token or not username or not client_id or not client_secret:
            print("[Twitch IRC] WARNUNG: Zugangsdaten (TOKEN, USERNAME, CLIENT_ID oder SECRET) fehlen. Twitch IRC Bot wird nicht gestartet.")
            return

        print(f"[Twitch IRC] Initialisiere Bot für User: {username}")

        # Bot ID holen (Erforderlich für twitchio 3.0)
        bot_id = await self._get_bot_id(username, token, client_id)
        if not bot_id:
            print("[Twitch IRC] FEHLER: Konnte die Twitch Bot-ID nicht ermitteln. IRC Bot wird nicht gestartet.")
            return

        # Lade Kanäle, denen der Bot beitreten soll
        channels = self.get_active_channels()
        print(f"[Twitch IRC] Aktive Kanäle aus Config: {channels}")
        
        # Falls keine Kanäle da sind, aber der Bot starten soll, nehmen wir den Bot-Acc selbst als Test
        if not channels:
            channels = [username]
            print(f"[Twitch IRC] Keine Kanäle konfiguriert, trete eigenem Kanal bei: {channels}")

        try:
            self.twitch_bot = TwitchChatBot(
                token=f"oauth:{token}" if not token.startswith("oauth:") else token,
                prefix="!",
                initial_channels=channels,
                discord_cog=self,
                client_id=client_id,
                client_secret=client_secret,
                bot_id=bot_id
            )
            
            print("[Twitch IRC] Starte Verbindungs-Task...")
            # Startet den Twitch Bot in der bestehenden Ereignisschleife
            self.bot.loop.create_task(self.twitch_bot.connect())
        except Exception as e:
            print(f"[Twitch IRC] Fehler beim Starten des Twitch-Bots: {e}")

    async def _get_bot_id(self, username: str, token: str, client_id: str) -> Optional[str]:
        """
        Holt die Twitch User ID für den Bot-Account.
        Wir nutzen Client Credentials (App Token) für den API-Call, 
        da das Bot-Token oft eine andere Client-ID hat (z.B. von TwitchApps).
        """
        import aiohttp
        client_secret = self.bot.config.get("TWITCH_CLIENT_SECRET")
        
        # 1. App Access Token holen
        auth_url = f"https://id.twitch.tv/oauth2/token?client_id={client_id}&client_secret={client_secret}&grant_type=client_credentials"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(auth_url) as auth_resp:
                    if auth_resp.status != 200:
                        print(f"[Twitch IRC] Konnte App-Token für ID-Check nicht generieren: {auth_resp.status}")
                        return None
                    auth_data = await auth_resp.json()
                    app_token = auth_data['access_token']

                # 2. User ID mit App Token abrufen
                headers = {
                    "Client-ID": client_id,
                    "Authorization": f"Bearer {app_token}"
                }
                url = f"https://api.twitch.tv/helix/users?login={username}"
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('data'):
                            return data['data'][0]['id']
                    else:
                        print(f"[Twitch IRC] API Fehler beim ID-Abruf (Helix): {response.status} - {await response.text()}")
        except Exception as e:
            print(f"[Twitch IRC] Netzwerkfehler beim ID-Abruf: {e}")
        return None

    def get_active_channels(self) -> List[str]:
        """Lädt die Liste der Kanäle, auf denen der Bot aktiv sein soll."""
        config = self.bot.data.load_json(self.config_path, {"channels": {}})
        return [c for c, data in config["channels"].items() if data.get("active", False)]

    def save_channel_config(self, channel_name: str, active: bool, guild_id: Optional[int] = None):
        """Speichert die Kanal-Konfiguration."""
        config = self.bot.data.load_json(self.config_path, {"channels": {}})
        config["channels"][channel_name.lower()] = {
            "active": active,
            "guild_id": guild_id
        }
        self.bot.data.save_json(self.config_path, config)
        
        # Wenn der Bot läuft, tritt er dem Kanal bei oder verlässt ihn
        if self.twitch_bot:
            if active:
                self.bot.loop.create_task(self.twitch_bot.join_channels([channel_name]))
            else:
                self.bot.loop.create_task(self.twitch_bot.part_channels([channel_name]))

    def save_custom_command(self, channel_name: str, command: str, response: str, permission: str = "everyone"):
        """Speichert einen benutzerdefinierten Befehl für einen Kanal."""
        config = self.bot.data.load_json(self.config_path, {"channels": {}})
        channel_name = channel_name.lower()
        
        if channel_name not in config["channels"]:
            config["channels"][channel_name] = {"active": False, "custom_commands": {}}
        
        if "custom_commands" not in config["channels"][channel_name]:
            config["channels"][channel_name]["custom_commands"] = {}
            
        config["channels"][channel_name]["custom_commands"][command.lower()] = {
            "response": response,
            "permission": permission
        }
        self.bot.data.save_json(self.config_path, config)

    def remove_custom_command(self, channel_name: str, command: str):
        """Entfernt einen benutzerdefinierten Befehl."""
        config = self.bot.data.load_json(self.config_path, {"channels": {}})
        channel_name = channel_name.lower()
        
        if channel_name in config["channels"] and "custom_commands" in config["channels"][channel_name]:
            config["channels"][channel_name]["custom_commands"].pop(command.lower(), None)
            self.bot.data.save_json(self.config_path, config)

    async def cog_unload(self):
        if self.twitch_bot:
            await self.twitch_bot.close()

async def setup(bot: commands.Bot):
    await bot.add_cog(TwitchChatBotCog(bot))
