import discord
from discord.ext import commands, tasks
import json
import random
from datetime import datetime, timezone, timedelta
import os
from typing import Optional, Tuple, List

class WordleCog(commands.Cog, name="Wordle"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Eine Auswahl an deutschen 5-Buchstaben-Wörtern
        self.words = [
            "APFEL", "BIRNE", "STERN", "STURM", "RADIO", "TISCH", "STUHL", "LAMPE", "FEUER", "WASSER",
            "PFUND", "STADT", "LANDS", "TRAUM", "GLÜCK", "ABEND", "MUSIK", "SPORT", "WAGEN", "BLUME",
            "REISE", "PREIS", "STROM", "DRAHT", "KRAFT", "KLEID", "GLAST", "BLATT", "WOLKE", "REGEN",
            "SONNE", "MONAT", "JAHRE", "GRUSS", "BRIEF", "MARKT", "KUNST", "SPIEL", "TRAIN", "VOGEL"
        ]
        
    def get_wordle_config(self, guild_id: int):
        return self.bot.data.get_guild_data(guild_id, "wordle_game") or {}

    def save_wordle_config(self, guild_id: int, data: dict):
        self.bot.data.save_guild_data(guild_id, "wordle_game", data)

    def _get_daily_word(self):
        # Seed basiert auf dem heutigen Datum
        seed = datetime.now(timezone.utc).strftime("%Y%m%d")
        random.seed(seed)
        return random.choice(self.words).upper()

    def _get_status_emoji(self, guess: str, target: str) -> str:
        result = []
        target_list = list(target)
        guess_list = list(guess)
        res = ["⬛"] * 5
        
        # Erst volle Treffer (Grün)
        for i in range(5):
            if guess_list[i] == target_list[i]:
                res[i] = "🟩"
                target_list[i] = None
                guess_list[i] = None
        
        # Dann Teil-Treffer (Gelb)
        for i in range(5):
            if guess_list[i] is not None:
                if guess_list[i] in target_list:
                    res[i] = "🟨"
                    target_list[target_list.index(guess_list[i])] = None
                    
        return "".join(res)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        config = self.get_wordle_config(message.guild.id)
        if not config or str(message.channel.id) != str(config.get("channel_id")):
            return

        content = message.content.strip().upper()
        
        # Prüfen ob es ein 5-Buchstaben Wort ist
        if len(content) != 5 or not content.isalpha():
            return

        # Game-Status laden
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        game_state = config.get("game_state", {})
        
        # Reset wenn neuer Tag
        if game_state.get("date") != today_str:
            target_word = self._get_daily_word()
            game_state = {
                "date": today_str,
                "target": target_word,
                "guesses": [],
                "solved": False,
                "participants": []
            }

        if game_state["solved"]:
            try: await message.delete()
            except: pass
            await message.channel.send(f"❌ {message.author.mention}, das heutige Wordle wurde bereits gelöst!", delete_after=5)
            return

        # Regeln prüfen
        user_id = str(message.author.id)
        
        # 1. Man darf nicht zweimal hintereinander raten
        if game_state["guesses"] and game_state["guesses"][-1]["user_id"] == user_id:
            try: await message.delete()
            except: pass
            await message.channel.send(f"❌ {message.author.mention}, du darfst nicht zweimal hintereinander raten!", delete_after=5)
            return

        # 2. Man darf nur einmal pro Tag raten
        if any(g["user_id"] == user_id for g in game_state["guesses"]):
            try: await message.delete()
            except: pass
            await message.channel.send(f"❌ {message.author.mention}, du hast heute bereits geraten!", delete_after=5)
            return

        # Rateversuch verarbeiten - Jetzt löschen wir die Nachricht des Users
        try: await message.delete()
        except: pass

        target = game_state["target"]
        emoji_res = self._get_status_emoji(content, target)
        
        game_state["guesses"].append({
            "user_id": user_id,
            "name": message.author.display_name,
            "word": content,
            "result": emoji_res
        })

        if content == target:
            game_state["solved"] = True
            
        # UI Update
        embed = discord.Embed(title=f"Wordle vom {today_str}", color=discord.Color.gold() if game_state["solved"] else discord.Color.blue())
        board_text = ""
        for g in game_state["guesses"]:
            board_text += f"`{g['word']}` {g['result']} - {g['name']}\n"
        embed.description = board_text
        
        if game_state["solved"]:
            embed.description += f"\n🎉 **GELÖST!** Das Wort war **{target}**."
        elif len(game_state["guesses"]) >= 6:
            embed.description += f"\n❌ **Gescheitert!** Das Wort war **{target}**."
            game_state["solved"] = True

        # Versuche die existierende Board-Nachricht zu bearbeiten
        last_msg_id = game_state.get("last_msg_id")
        board_sent = False
        if last_msg_id:
            try:
                msg = await message.channel.fetch_message(last_msg_id)
                await msg.edit(embed=embed)
                board_sent = True
            except:
                pass
        
        if not board_sent:
            new_msg = await message.channel.send(embed=embed)
            game_state["last_msg_id"] = new_msg.id
        
        # Speichern
        config["game_state"] = game_state
        self.save_wordle_config(message.guild.id, config)

    # Web-API Methoden
    async def web_set_config(self, guild_id: int, channel_id: Optional[int]) -> Tuple[bool, str]:
        config = self.get_wordle_config(guild_id)
        config["channel_id"] = channel_id
        self.save_wordle_config(guild_id, config)
        return True, "Wordle Kanal wurde aktualisiert."

async def setup(bot: commands.Bot):
    await bot.add_cog(WordleCog(bot))
