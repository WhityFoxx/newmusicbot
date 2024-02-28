# imports
import discord
from discord import FFmpegPCMAudio
import bot_api.yandex_music as api
import httpx
from discord.utils import format_dt
from discord import Embed
import datetime
from config import TOKEN

bot = discord.Bot(intents=discord.Intents.all())

bot.load_extension('yandex_music_support')
bot.run(TOKEN) 
