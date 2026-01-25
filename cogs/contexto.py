import discord
from discord.ext import commands
import random
import json
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, List
import hashlib

class ContextoCog(commands.Cog, name="Contexto"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Eine Liste von Wörtern für das Spiel
        self.words = [
            "HAUS", "BAUM", "AUTO", "FLUSS", "BERGEN", "SONNE", "KAFFEE", "COMPUTER", "SCHULE", "URLAUB",
            "REISE", "WINTER", "SOMMER", "KÜCHE", "HANDY", "SPIEL", "STADT", "FREUND", "FAMILIE", "ESSEN"
        ]
        # Ein kleiner "semantischer" Cluster-Weg
        self.associations = {
            "GARTEN": ["BAUM", "PFLANZE", "WIESE", "ERDE", "NATUR"],
            "VERKEHR": ["AUTO", "STRASSE", "AMPEL", "REISE", "FAHREN"],
            "WETTER": ["SONNE", "REGEN", "WOLKE", "WINTER", "SOMMER", "HITZE"],
            "TECHNIK": ["COMPUTER", "HANDY", "INTERNET", "STROM", "RADIO"],
            "GEBÄUDE": ["HAUS", "SCHULE", "KÜCHE", "FENSTER", "TÜR"]
        }

    def get_contexto_config(self, guild_id: int):
        return self.bot.data.get_guild_data(guild_id, "contexto_game") or {}

    def save_contexto_config(self, guild_id: int, data: dict):
        self.bot.data.save_guild_data(guild_id, "contexto_game", data)

    def _calculate_similarity(self, guess: str, target: str) -> int:
        """
        Berechnet einen 'Rang' basierend auf Ähnlichkeit.
        1 = Perfekt, Höher = Weiter weg.
        Hier nutzen wir eine Mischung aus Dice-Koeffizient und semantischen Clustern.
        """
        guess = guess.upper()
        target = target.upper()
        
        if guess == target:
            return 1
            
        # Dice Coefficient (Sørensen–Dice) für Buchstaben-Ähnlichkeit
        def get_bigrams(word):
            return {word[i:i+2] for i in range(len(word)-1)}
            
        b1 = get_bigrams(guess)
        b2 = get_bigrams(target)
        
        if not b1 or not b2:
            dice = 0
        else:
            intersection = len(b1 & b2)
            dice = (2 * intersection) / (len(b1) + len(b2))
            
        # Semantischer Bonus
        semantic_bonus = 0
        for cluster, words in self.associations.items():
            if guess in words and target in words:
                semantic_bonus = 0.3
                break
            elif guess == cluster and target in words:
                semantic_bonus = 0.5
                break
            elif target == cluster and guess in words:
                semantic_bonus = 0.5
                break
        
        score = dice + semantic_bonus
        # Mapping von Score (0 bis 1.5) auf Rang (2 bis 5000)
        # Je höher der Score, desto niedriger der Rang
        rank = int(5000 * (1 - min(score, 1.0) * 0.95)) + 2
        
        # Ein bisschen Rauschen basierend auf dem Wort-Hash für Konsistenz
        noise = int(hashlib.mdsafe(guess.encode()).hexdigest(), 16) % 50
        return max(2, rank + noise)

    def _get_daily_word(self):
        seed = datetime.now(timezone.utc).strftime("%Y%m%d")
        random.seed(seed)
        return random.choice(self.words).upper()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        config = self.get_contexto_config(message.guild.id)
        if not config or str(message.channel.id) != str(config.get("channel_id")):
            return

        content = message.content.strip().upper()
        if not content.isalpha() or len(content) < 2:
            return

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        game_state = config.get("game_state", {})
        
        # Reset bei neuem Tag
        if game_state.get("date") != today_str:
            game_state = {
                "date": today_str,
                "target": self._get_daily_word(),
                "guesses": [],
                "solved": False
            }

        if game_state["solved"]:
            return # Bereits gelöst

        # Rang berechnen
        target = game_state["target"]
        rank = self._calculate_similarity(content, target)
        
        # Fortschrittsbalken oder Indikator
        indicator = "🔴" # Kalt
        if rank < 100: indicator = "🔥" # Heiß
        elif rank < 500: indicator = "🟧" # Warm
        elif rank < 1500: indicator = "🟨" # Lauwarm
        
        if rank == 1:
            game_state["solved"] = True
            msg = f"🎉 **{message.author.display_name}** hat das Wort erraten! Es war **{target}**! 🏆"
            indicator = "✅"
        else:
            msg = f"**{content}** | Rang: `{rank}` {indicator}"

        # In Liste speichern
        game_state["guesses"].append({
            "user": message.author.display_name,
            "word": content,
            "rank": rank
        })
        # Sortiere guesses nach Rang für das Dashboard
        game_state["guesses"] = sorted(game_state["guesses"], key=lambda x: x["rank"])[:50]

        await message.reply(msg)
        
        config["game_state"] = game_state
        self.save_contexto_config(message.guild.id, config)

    async def web_set_config(self, guild_id: int, channel_id: Optional[int]) -> Tuple[bool, str]:
        config = self.get_contexto_config(guild_id)
        config["channel_id"] = channel_id
        self.save_contexto_config(guild_id, config)
        return True, "Contexto Kanal wurde aktualisiert."

async def setup(bot: commands.Bot):
    # Hilfsfunktion für Hash (wird in Python 3.11+ benötigt falls hashlib.md5 gesperrt ist)
    if not hasattr(hashlib, 'mdsafe'):
        hashlib.mdsafe = hashlib.md5
    await bot.add_cog(ContextoCog(bot))
