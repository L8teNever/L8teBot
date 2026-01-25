# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import twitchio
from twitchio.ext import commands as t_commands
import asyncio
import os
import json
from typing import List, Optional
import datetime
import asyncio

from twitchio import eventsub

class TwitchChatBot(t_commands.Bot):
    def __init__(self, token, prefix, initial_channels, discord_cog, client_id, client_secret, bot_id):
        # In TwitchIO 3.x, token should be just the string (without oauth:)
        clean_token = token.replace("oauth:", "")
        super().__init__(
            token=clean_token, 
            prefix=prefix, 
            client_id=client_id,
            client_secret=client_secret,
            bot_id=bot_id
        )
        self.discord_cog = discord_cog
        self.initial_channels_names = initial_channels or []

    async def event_ready(self):
        print(f'[Twitch IRC] Bot eingeloggt als | {self.user.name}')
        
        # Subscribe to initial channels via EventSub
        if self.initial_channels_names:
            try:
                print(f"[Twitch IRC] Resolving IDs for channels: {self.initial_channels_names}")
                users = await self.fetch_users(logins=self.initial_channels_names)
                for user in users:
                    await self.join_target_channel(user)
                print(f'[Twitch IRC] Initial subscriptions completed.')
            except Exception as e:
                print(f"[Twitch IRC] Fehler beim Verbinden mit initialen Kanälen: {e}")
                import traceback
                traceback.print_exc()

    async def join_target_channel(self, user):
        """Subscribes to chat messages for a specific user (broadcaster)."""
        try:
            # We need broadcaster_user_id (the channel) and user_id (the bot)
            payload = eventsub.ChatMessageSubscription(broadcaster_user_id=user.id, user_id=self.bot_id)
            await self.subscribe_websocket(payload=payload)
            print(f"[Twitch IRC] Joined channel {user.name} ({user.id}) via EventSub")
        except Exception as e:
            # Check if it is "already exists" error, which we can ignore
            if "already exists" in str(e):
                pass
            else:
                print(f"[Twitch IRC] Error joining channel {user.name}: {e}")

    async def part_target_channel(self, user):
        """Unsubscribes from chat messages for a specific user."""
        try:
            # Find subscription
            # Filter by broadcaster (user_id argument in fetch_eventsub_subscriptions works as filter for condition user_id?)
            # Actually, per docs: "Filter subscriptions by user ID... The response contains subscriptions where this ID matches a user ID that you specified in the Condition object"
            # ChatMessageSubscription condition has user_id (bot for us?) and broadcaster_user_id (channel).
            # Let's try to fetch all enabled chat message subscriptions and filter manually to be safe, or try to filter by type.
            
            subs = await self.fetch_eventsub_subscriptions(type='channel.chat.message', status='enabled')
            target_sub = None
            for sub in subs:
                # Condition keys are strings. 
                # For ChatMessageSubscription: broadcaster_user_id, user_id
                if sub.condition.get('broadcaster_user_id') == str(user.id) and sub.condition.get('user_id') == str(self.bot_id):
                    target_sub = sub
                    break
            
            if target_sub:
                await self.delete_eventsub_subscription(target_sub.id)
                print(f"[Twitch IRC] Parted channel {user.name}")
            else:
                print(f"[Twitch IRC] No active subscription found for {user.name}")
                
        except Exception as e:
            print(f"[Twitch IRC] Error parting channel {user.name}: {e}")

    async def join_channel_by_name(self, channel_name: str):
        try:
            users = await self.fetch_users(logins=[channel_name])
            if users:
                await self.join_target_channel(users[0])
            else:
                print(f"[Twitch IRC] Channel not found: {channel_name}")
        except Exception as e:
            print(f"[Twitch IRC] Error resolving channel {channel_name}: {e}")

    async def part_channel_by_name(self, channel_name: str):
        try:
            users = await self.fetch_users(logins=[channel_name])
            if users:
                await self.part_target_channel(users[0])
            else:
                print(f"[Twitch IRC] Channel not found: {channel_name}")
        except Exception as e:
            print(f"[Twitch IRC] Error resolving channel {channel_name}: {e}")

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
        self.creds_path = os.path.join(DATA_DIR, "twitch_bot_creds.json")
        self.bot.loop.create_task(self.initialize_twitch_bot())

    def get_bot_identity(self):
        """Gibt Infos zum verknüpften Bot-Account zurück."""
        creds = self.bot.data.load_json(self.creds_path)
        if creds and "user" in creds:
            return creds["user"]
        return None

    def save_bot_creds(self, token_data, user_data):
        """Speichert die Tokens und User-Infos für den Bot-Account."""
        data = {
            "tokens": token_data,
            "user": user_data,
            "updated_at": datetime.datetime.now().isoformat()
        }
        self.bot.data.save_json(self.creds_path, data)
        # Bot neu starten mit neuen Creds (Thread-sicher da Aufruf von Flask kommt)
        asyncio.run_coroutine_threadsafe(self.initialize_twitch_bot(), self.bot.loop)

    async def _refresh_bot_token(self):
        """Erneuert das Bot-Token mittels Refresh-Token."""
        import aiohttp
        creds = self.bot.data.load_json(self.creds_path)
        if not creds or "tokens" not in creds:
            return None
            
        refresh_token = creds["tokens"].get("refresh_token")
        client_id = self.bot.config.get("TWITCH_CLIENT_ID")
        client_secret = self.bot.config.get("TWITCH_CLIENT_SECRET")
        
        if not refresh_token or not client_id or not client_secret:
            return None

        url = "https://id.twitch.tv/oauth2/token"
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data) as resp:
                    if resp.status == 200:
                        new_tokens = await resp.json()
                        creds["tokens"].update(new_tokens)
                        creds["updated_at"] = datetime.datetime.now().isoformat()
                        self.bot.data.save_json(self.creds_path, creds)
                        return new_tokens["access_token"]
                    else:
                        print(f"[Twitch IRC] Token Refresh fehlgeschlagen: {resp.status}")
        except Exception as e:
            print(f"[Twitch IRC] Fehler beim Token Refresh: {e}")
        return None

    async def initialize_twitch_bot(self):
        """Initialisiert den Twitch Bot IRC Client."""
        await self.bot.wait_until_ready()
        
        # Falls ein Bot läuft, erst beenden
        if self.twitch_bot:
            try: await self.twitch_bot.close()
            except: pass

        creds = self.bot.data.load_json(self.creds_path)
        client_id = self.bot.config.get("TWITCH_CLIENT_ID")
        client_secret = self.bot.config.get("TWITCH_CLIENT_SECRET")
        
        if not creds or "tokens" not in creds:
            print("[Twitch IRC] Kein Bot-Account verknüpft. Bitte im Dashboard einrichten.")
            return

        token = creds["tokens"]["access_token"]
        username = creds["user"]["login"]
        bot_id = creds["user"]["id"]

        print(f"[Twitch IRC] Initialisiere Bot für User: {username}")

        # Lade Kanäle, denen der Bot beitreten soll
        channels = self.get_active_channels()
        if not channels:
            channels = [username]

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
            self.bot.loop.create_task(self.twitch_bot.start())
        except Exception as e:
            print(f"[Twitch IRC] Fehler beim Starten des Twitch-Bots: {e}")
            import traceback
            traceback.print_exc()

    def get_active_channels(self) -> List[str]:
        """Lädt die Liste der Kanäle, auf denen der Bot aktiv sein soll."""
        config = self.bot.data.load_json(self.config_path, {"channels": {}})
        return [c for c, data in config["channels"].items() if data.get("active", False)]

    def save_channel_config(self, channel_name: str, active: bool, guild_id: Optional[int] = None):
        """Speichert die Kanal-Konfiguration."""
        config = self.bot.data.load_json(self.config_path, {"channels": {}})
        channel_name = channel_name.lower()
        
        if channel_name not in config["channels"]:
            config["channels"][channel_name] = {"active": False, "custom_commands": {}}
        
        config["channels"][channel_name]["active"] = active
        if guild_id: config["channels"][channel_name]["guild_id"] = guild_id
            
        self.bot.data.save_json(self.config_path, config)
        
        if self.twitch_bot:
            async def perform_action_safe(action, name):
                try:
                    target = self.twitch_bot
                    if action == "join":
                         await target.join_channel_by_name(name)
                    else:
                         await target.part_channel_by_name(name)
                except Exception as e:
                    print(f"[Twitch IRC] Fehler beim {action} von {name}: {e}")

            if active:
                asyncio.run_coroutine_threadsafe(perform_action_safe("join", channel_name), self.bot.loop)
            else:
                asyncio.run_coroutine_threadsafe(perform_action_safe("part", channel_name), self.bot.loop)

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
