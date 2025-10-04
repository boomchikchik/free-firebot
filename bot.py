from pyrogram import Client, idle
from pyromod import Client as modClient

from vars import *

class Zoro(Client):
    def __init__(self):
        self.bot: modClient = modClient(
            "Zoro",
            API_ID,
            API_HASH,
            plugins=dict(root="plugins"),
            bot_token=BOT_TOKEN
        )
        

    async def start_bot(self):
        await self.bot.start()
        print(f"@{self.bot.me.username} is alive now!")
        
    async def stop(self):
        await self.bot.stop()
        print("Bot is dead now")

    async def start_up(self):
        await self.start_bot()
        await idle()


marimo = Zoro()
