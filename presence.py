import itertools
import discord
from discord.ext import commands, tasks

STATUSES = ["↪ Dead by bodrios", "↪ Dev: Supskevv"]


class Presence(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._cycle = itertools.cycle(STATUSES)
        self.rotate_status.start()

    def cog_unload(self):
        self.rotate_status.cancel()

    @tasks.loop(seconds=10)
    async def rotate_status(self):
        text = next(self._cycle)
        await self.bot.change_presence(activity=discord.CustomActivity(name=text))

    @rotate_status.before_loop
    async def before_rotate(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Presence(bot))
