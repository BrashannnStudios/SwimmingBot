import os
import asyncio
import discord
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
from flask import Flask
from threading import Thread

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
MONGO_URI = os.environ["MONGO_URI"]

EMBED_COLOR = 0xCEF3F1
FOOTER_TEXT = "Swimming for Animals"

EMOJIS = {
    "reloj": "<:RelojEmoji:0>",
    "reloj_arena": "<:RelojArenaEmoji:0>",
    "pluma": "<:PlumaEmoji:0>",
    "lupa": "<:Lupaemoji:0>",
    "denegado": "<:DenegadoEmoji:0>",
    "aviso": "<:AvisoEmoji:0>",
    "aceptar": "<:Aceptar:0>",
}

# ---------- Keep-alive Flask (para Render) ----------
app = Flask(__name__)


@app.route("/")
def home():
    return "Swimming for Animals bot está vivo."


def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))


def keep_alive():
    Thread(target=run_flask, daemon=True).start()


# ---------- Bot ----------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True


class DeadByBodrios(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or("?"),
            intents=intents,
            case_insensitive=True,
            help_command=None,
        )
        self.mongo = AsyncIOMotorClient(MONGO_URI)
        self.db = self.mongo["dead_by_bodrios"]
        self.embed_color = EMBED_COLOR
        self.footer_text = FOOTER_TEXT
        self.custom_emojis = EMOJIS

        # Caches en memoria para no golpear Mongo en cada mensaje
        self.guild_config_cache = {}   # guild_id -> dict (bot-setup)
        self.flood_tracker = {}        # guild_id -> {user_id: [timestamps]}

    async def setup_hook(self):
        await self.load_extension("commands")
        await self.load_extension("welcome")
        await self.load_extension("tickets")
        await self.load_extension("presence")
        await self.load_extension("appeals")

        try:
            await self.tree.sync()
        except Exception as e:
            print(f"Error sincronizando slash commands: {e}")

    async def on_ready(self):
        print(f"[Swimming for Animals] Conectado como {self.user} (ID: {self.user.id})")


bot = DeadByBodrios()


async def main():
    keep_alive()
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
