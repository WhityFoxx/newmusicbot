import discord
from discord.ext import commands
from discord import Embed
from discord import FFmpegPCMAudio
import bot_api.yandex_music as api
import httpx
import asyncio
import datetime
from bot_api.models import *
import re
import random
import time
from discord.ext import pages
from discord import Color
from config import session_id
PLAYLIST_RE = re.compile(r'([\w\-._]+)/playlists/(\d+)$')
def args_playlist_id(arg: str) -> PlaylistId:
    print(arg)
    arr = arg.split('/')
    return PlaylistId(owner=arr[0], kind=int(arr[1]))   
DEFAULT_USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/106.0.0.0 Safari/537.36'
MD5_SALT = 'XGRlBW9FXlekgbPrRHuSiA'

ffmpeg_options = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'}

queue = {} 
loop_status = {}
class YandexMusic(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    @commands.Cog.listener()
    async def on_ready(self):
        print("ready")


    async def play_song(self, about, ctx, msg):
            if msg != None:
                try:
                    await msg.edit(view=None)
                except discord.errors.HTTPException:
                    msg = await ctx.channel.get_partial_message(msg.id).fetch()
                    await msg.edit(view=None)
            if about is None:
                return
            if about['stream'] is None:
                async with httpx.AsyncClient() as client:
                    session = await api.setup_session(session=client, session_id=session_id, user_agent=DEFAULT_USER_AGENT)
                    stream = FFmpegPCMAudio(await api.get_track_download_url_pe(session=session, track=about['data'], hq=True), **ffmpeg_options)
            else:
                stream = FFmpegPCMAudio(about['stream'], **ffmpeg_options)
            embed = Embed(title=' & '.join([x.name for x in about['data'].artists]) + " - " + about['data'].title, url=about['url'])
            embed.add_field(name="Длительность", value=datetime.timedelta(seconds=about['data'].duration // 1000), inline=False)
            embed.set_thumbnail(url=about['data'].cover_info.cover_url_template[:-2:] + 'm400x400')
            try:
                msg = await ctx.respond(embed=embed, view=MyView())
            except discord.errors.HTTPException:
                msg = await ctx.send(embed=embed, view=MyView())
            vc = ctx.guild.voice_client
            vc.play(stream, after=lambda e: self.next_song(e, ctx, msg))
            if loop_status[ctx.guild.id] == True:
                queue[ctx.guild.id].insert(0, about)
    def next_song(self, error, ctx, msg):
        global queue
        try:
            next_song = queue[ctx.guild.id].pop(0)
        except IndexError:
            next_song = None

        self.current_song = None
        coro = self.play_song(next_song, ctx, msg)
        self.bot.loop.create_task(coro)
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        if after.channel == None and member.id == self.bot.user.id:
            queue[member.guild.id] = []
            loop_status[member.guild.id] = False

            member.guild.voice_client.stop()
    @commands.slash_command(name='play')
    async def play(self, ctx : discord.ApplicationContext, requests:discord.Option(str, 'Ссылка')):
        global queue
        await ctx.defer()
        # Чекер
        if ctx.author.voice == None:
            emb = Embed(description=f"**Вы не в канале!**", color=0x2ecc71)
            await ctx.respond(embed=emb, ephemeral=True)
            return
        if ctx.voice_client == None:
            queue[ctx.guild.id] = []
            loop_status[ctx.guild.id] = False
            await ctx.author.voice.channel.connect()
        if ctx.author.voice.channel != ctx.voice_client.channel and ctx.voice_client != None:
            emb = Embed(title=f"Вы в разных с ботом каналах", color=0x2ecc71)
            await ctx.respond(embed=emb, ephemeral=True)
            return
        # Обработка запроса
        if 'music.yandex.ru' not in requests:
            async with httpx.AsyncClient() as client:
                session = await api.setup_session(session=client, session_id=session_id, user_agent=DEFAULT_USER_AGENT)
                url = await api.get_track_by_name(session, requests)
                track = {"album_id": url.split("track/")[-1], "id":  url.split('album/')[-1].split('/track')[0]}
                session = await api.setup_session(session=client, session_id=session_id, user_agent=DEFAULT_USER_AGENT)
                data = await api.get_full_track_info(session, track_id=track['album_id']) 
                queue[ctx.guild.id].append({'url': url ,'data' :data, 'stream': await api.get_track_download_url(session=session, track=track, hq=True), 'author': ctx.author})
        elif '/playlists' in requests:
            async with httpx.AsyncClient() as client:
                if match := PLAYLIST_RE.search(requests):
                    playlist_id = PlaylistId(owner=match.group(1), kind=int(match.group(2)))
                    session = await api.setup_session(session=client, session_id=session_id, user_agent=DEFAULT_USER_AGENT)
                    playlist = await api.get_playlist(client, playlist_id)
                    
                    data_to_add = [{'url': f"https://music.yandex.ru/album/{data.album.id}/track/{data.id}", 'data' : data, 'stream': None, 'author': ctx.author} for data in playlist]
                    queue[ctx.guild.id].extend(data_to_add)
                    
                await ctx.respond(embed=Embed(description=f'Плейлист, состоящий из {len(data_to_add)} треков добавлен в очередь'))
        else:
            track = {"album_id": requests.split("track/")[-1], "id":  requests.split('album/')[-1].split('/track')[0]}
            async with httpx.AsyncClient() as client:
                session = await api.setup_session(session=client, session_id=session_id, user_agent=DEFAULT_USER_AGENT)
                data = await api.get_full_track_info(session, track_id=track['album_id']) 
                queue[ctx.guild.id].append({'url': requests, 'data' :data, 'stream': await api.get_track_download_url(session=session, track=track, hq=True), 'author': ctx.author})
        # Исполнение запроса
        if ctx.voice_client.is_playing():
            lastest = queue[ctx.guild.id][-1]
            if lastest['stream'] == None:
                return
            await ctx.respond(embed=Embed(description=f'[{lastest["data"].title}]({lastest["url"]}) добавлена в очередь'))
            return

        async with ctx.typing():
            self.next_song('xd', ctx=ctx, msg=None)
"""        while True:
            about = queue[ctx.guild.id].pop(0)
            data = about['data']
            vc = ctx.voice_client
            if about['stream'] is None:
                async with httpx.AsyncClient() as client:
                    session = await api.setup_session(session=client, session_id=session_id, user_agent=DEFAULT_USER_AGENT)
                    stream = FFmpegPCMAudio(await api.get_track_download_url_pe(session=session, track=data, hq=True), **ffmpeg_options)
            else:
                stream = FFmpegPCMAudio(about['stream'], **ffmpeg_options)
            async with ctx.typing():

                vc.play(stream, after=lambda e: self.next_song(e, ctx.guild.id))
                embed = Embed(title=' & '.join([x.name for x in data.artists]) + " - " + data.title, url=about['url'])
                embed.add_field(name="Длительность", value=datetime.timedelta(seconds=data.duration // 1000), inline=False)
                embed.set_thumbnail(url=data.cover_info.cover_url_template[:-2:] + 'm400x400')
                try:
                    msg = await ctx.respond(embed=embed, view=MyView())
                except discord.errors.HTTPException:
                    msg = await ctx.send(embed=embed, view=MyView())
            while vc.is_playing() or vc.is_paused():
                await asyncio.sleep(5)
            if loop_status[ctx.guild.id] == True:
                queue[ctx.guild.id].insert(0, about)
            try:
                await msg.edit( view=None)
            except discord.errors.HTTPException:
                msg = await ctx.channel.get_partial_message(msg.id).fetch()
                await msg.edit( view=None)
            if queue[ctx.guild.id] == []:
                break
           """ 
class MyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(emoji='⏩', row=0, style=discord.ButtonStyle.primary)
    async def skip_button(self, button, interaction):
        global loop_status
        embed_from = interaction.message.embeds[0]
        server = interaction.message.guild
        voice_clients = server.voice_client
        if voice_clients == None:
            emb = Embed(description=f"**Бот не в канале**", color=0x2ecc71)
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        elif interaction.user.voice == None:
            emb = Embed(description=f"**Вы не в канале!**", color=0x2ecc71)
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        elif interaction.user.voice.channel != voice_clients.channel:
            emb = Embed(description=f"**Вы в разных каналах!**", color=0x2ecc71)
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        loop_status[interaction.guild_id] = False
        voice_clients.stop()
        emb = Embed(title=embed_from.title, url=embed_from.url, description=embed_from.description,
                    timestamp=interaction.message.created_at, color=0xe74c3c)
        emb.add_field(name="Длительность", value=embed_from.fields[0].value, inline=False)

        emb.set_thumbnail(url=embed_from.thumbnail.url)

        emb.set_footer(text=f"Пропущено {interaction.user.name}")
        await interaction.response.edit_message(embed=emb, view=None)

    @discord.ui.button(emoji='⏸️', row=0, style=discord.ButtonStyle.primary)
    async def pause_button(self, button, interaction):
        server = interaction.message.guild
        voice_clients = server.voice_client
        if voice_clients == None:
            emb = Embed(description=f"**Бот не в канале**", color=0x2ecc71)
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        elif interaction.user.voice == None:
            emb = Embed(description=f"**Вы не в канале!**", color=0x2ecc71)
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        elif interaction.user.voice.channel != voice_clients.channel:
            emb = Embed(description=f"**Вы в разных каналах!**", color=0x2ecc71)
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        embed_from = interaction.message.embeds[0]

        voice_clients.pause()
        emb = Embed(title=embed_from.title, url=embed_from.url, description=embed_from.description,
                    timestamp=interaction.message.created_at, color=0xf1c40f)
        emb.add_field(name="Длительность", value=embed_from.fields[0].value, inline=False)
        emb.set_thumbnail(url=embed_from.thumbnail.url)

        emb.set_footer(text=f"Приостановлено {interaction.user.name}")
        await interaction.response.edit_message(embed=emb, view=self)

    @discord.ui.button(emoji='▶️', row=0, style=discord.ButtonStyle.primary)
    async def resume_button(self, button, interaction):
        server = interaction.message.guild
        voice_clients = server.voice_client
        if voice_clients == None:
            emb = Embed(description=f"**Бот не в канале**", color=0x2ecc71)
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        elif interaction.user.voice == None:
            emb = Embed(description=f"**Вы не в канале!**", color=0x2ecc71)
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        elif interaction.user.voice.channel != voice_clients.channel:
            emb = Embed(description=f"**Вы в разных каналах!**", color=0x2ecc71)
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        if voice_clients.is_paused() == False:
            await interaction.response.edit_message()
            return
        embed_from = interaction.message.embeds[0]
        voice_clients.resume()
        emb = Embed(title=embed_from.title, url=embed_from.url,
                    description=embed_from.description, timestamp=interaction.message.created_at, color=0x2ecc71)
        emb.add_field(name="Длительность", value=embed_from.fields[0].value, inline=False)
        emb.set_thumbnail(url=embed_from.thumbnail.url)

        emb.set_footer(text=f"Возобновлено {interaction.user.name}")
        await interaction.response.edit_message(embed=emb, view=self)

    @discord.ui.button(emoji='🔀', row=1, style=discord.ButtonStyle.primary)
    async def shuffle_button(self, button, interaction):
        global queue
        server = interaction.message.guild
        voice_clients = server.voice_client
        if voice_clients == None:
            emb = Embed(description=f"**Бот не в канале**", color=0x2ecc71)
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        elif interaction.user.voice == None:
            emb = Embed(description=f"**Вы не в канале!**", color=0x2ecc71)
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        elif interaction.user.voice.channel != voice_clients.channel:
            emb = Embed(description=f"**Вы в разных каналах!**", color=0x2ecc71)
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        embed_from = interaction.message.embeds[0]
        if queue[interaction.guild_id] == []:
            emb = Embed(title=f"Очередь пуста", color=0xe74c3c, timestamp=interaction.message.created_at)

            msg = await interaction.response.send_message(embed=emb, ephemeral=True)
        else:
            random.shuffle(queue[interaction.guild_id])
            emb = Embed(title=f"Очередь перемешена", color=0xe74c3c, timestamp=interaction.message.created_at)

            msg = await interaction.response.send_message(embed=emb, ephemeral=True)

    @discord.ui.button(emoji='🔃', row=1, style=discord.ButtonStyle.primary)
    async def loop_button(self, button, interaction):
        global loop_status
        server = interaction.message.guild
        voice_clients = server.voice_client
        if voice_clients == None:
            emb = Embed(description=f"**Бот не в канале**", color=0x2ecc71)
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        elif interaction.user.voice == None:
            emb = Embed(description=f"**Вы не в канале!**", color=0x2ecc71)
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        elif interaction.user.voice.channel != voice_clients.channel:
            emb = Embed(description=f"**Вы в разных каналах!**", color=0x2ecc71)
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        if loop_status[interaction.guild_id] == False:
            loop_status[interaction.guild_id] = True
        else:
            loop_status[interaction.guild_id] = False
        embed_from = interaction.message.embeds[0]
        if loop_status[interaction.guild_id] == True:
            emb = Embed(title=embed_from.title, url=embed_from.url,
                        description=embed_from.description, timestamp=interaction.message.created_at, color=0x2ecc71)
            emb.add_field(name="Длительность", value=embed_from.fields[0].value, inline=False)
            emb.set_thumbnail(url=embed_from.thumbnail.url)

            emb.set_footer(text=f"Зациклено {interaction.user.name}")
            await interaction.response.edit_message(embed=emb)
        else:
            emb = Embed(title=embed_from.title, url=embed_from.url,
                        description=embed_from.description, timestamp=interaction.message.created_at, color=0x2ecc71)
            emb.add_field(name="Длительность", value=embed_from.fields[0].value, inline=False)

            emb.set_footer(text=f"Разциклено {interaction.user.name}")
            await interaction.response.edit_message(embed=emb)
    @discord.ui.button(label='📜', row=1, style=discord.ButtonStyle.primary)
    async def queue(self, button, interaction):
        if queue[interaction.guild.id] == []:
            emb = Embed(description='Очередь **пуста**!', color=0x0c0c0c)
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        emb = Embed(title='Выберите действие с очередью', description='👁️ - **просмотр очереди** \n\n🗑️ - **очистка очереди**\n\n✂ - **удаление определенной композиции**\n\n📥 - **вставить композицию в очередь**\n\n⭕ - **выделить композицию и взаимодействовать с ней\n\n🔀 - перемешать очередь **', color=0x0c0c0c)
        emb.set_footer(text='Таймаут меню 30 секунд!')
        await interaction.response.send_message(embed=emb, view=Queue(), ephemeral=True)
async def vc_check(author, bot_voice):

    if bot_voice == None:
        return Embed(description=f"**Бот, к сожалению, не подключен к каналу, {author.name}!**", color=0xe74c3c)
    elif author.voice is None:
        return Embed(description=f"**Вы не в канале, {author.name}!**", color=Color.red())
    elif author.voice.channel != bot_voice.channel:
        return Embed(description=f"**Вы в разных каналах с ботом, {author.name}!**", color=Color.red())
class SendModalSelect(discord.ui.View):
    @discord.ui.button(label="Выбрать композицию", emoji='✅', row=1, style=discord.ButtonStyle.primary)
    async def send_modal_queue(self, button, interaction):
        await interaction.response.send_modal(QueueSelect(title='Введите имя композиции'))
class Queue(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=20)
        self.avatar = "https://yt3.ggpht.com/ytc/AKedOLQPLgvRGHtuxEazcF7UXJRJe7WmpToMlnygCfLt=s900-c-k-c0x00ffffff-no-rj"
    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        await self.message.edit(view=self)
    @discord.ui.button(emoji='👁️', row=0, style=discord.ButtonStyle.primary)
    async def show_queue(self, button, interaction):
        global queue
        desc = ''
        pagess = []
        steps = 0
        for i in queue[interaction.guild.id]:
            steps += 1
            if len(desc) > 1024:
                emb = Embed(title=f"Очередь музыкального бота", description=f"{desc}", color=Color.blue())
                pagess.append(emb)
                desc = ''
            desc += f"{steps}. [{str(i['data'].title)}]({i['url']}) | *{str(i['author'])}* \n"
        pagess.append(Embed(title=f"**Очередь музыкального бота**", description=desc, color=0xe74c3c))
        paginator = pages.Paginator(pages=pagess, disable_on_timeout=True, timeout=30)
        await paginator.respond(interaction, ephemeral=True)
        return
    @discord.ui.button(emoji='🗑️', row=0, style=discord.ButtonStyle.primary)
    async def clear_queue(self, button, interaction):
        global queue
        if queue[interaction.guild.id] == []:
            emb = Embed(description='Очередь **пуста**!', color=0x0c0c0c)
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        await interaction.response.send_message(embed=Embed(description=f'**Вы точно хотите очистить очередь? (Да/Нет)**', color=0x0c0c0c),
                          ephemeral=True, view=QueueClear())
    @discord.ui.button(emoji='✂', row=0, style=discord.ButtonStyle.primary)
    async def delete_in_queue(self, button, interaction):
        if queue[interaction.guild.id] == []:
            emb = Embed(description='Очередь **пуста**!', color=0x0c0c0c)
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        desc = ''
        pagess = []
        steps = 0
        for i in queue[interaction.guild.id]:
            steps += 1
            if len(desc) > 1024:
                emb = Embed(title=f"{interaction.user.name}, выберите композицию и нажмите на кнопку ниже",
                            description=f"{desc}", color=Color.blue())
                pagess.append(emb)
                desc = ''
            desc += f"{steps}. [{str(i['data'].title)}]({i['url']}) | *{str(i['author'])}* \n"
        pagess.append(Embed(title=f"**Очередь музыкального бота**", description=desc, color=0xe74c3c))
        paginator = pages.Paginator(pages=pagess, disable_on_timeout=True, timeout=30, custom_view=SendMlDelQe())
        await paginator.respond(interaction, ephemeral=True)
    @discord.ui.button(emoji='📥', row=1, style=discord.ButtonStyle.primary)
    async def insert(self, button, interaction):
        if queue[interaction.guild.id] == []:
            emb = Embed(description='Очередь **пуста**!', color=0x0c0c0c)
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return
        await interaction.response.send_modal(QueueInsert(title="Вставка композиции"))

    @discord.ui.button(emoji='⭕', row=1, style=discord.ButtonStyle.primary)
    async def select(self, button, interaction):
        global queue
        if queue[interaction.guild.id] == []:
            emb = Embed(title=f"Очередь пуста!", color=Color.blue())
            interaction.response.send_message(embed=emb, ephemeral=True)
            return
        desc = ''
        pagess = []
        steps = 0
        for i in queue[interaction.guild.id]:
            steps += 1
            if len(desc) > 1024:
                emb = Embed(title=f"**Выберите номер композиции**", description=f"{desc}", color=Color.blue())
                pagess.append(emb)
                desc = ''
            desc += f"{steps}. [{str(i['data'].title)}]({i['url']}) | *{str(i['author'])}* \n"
        pagess.append(Embed(title=f"**Выберите номер композиции**", description=desc, color=0xe74c3c))
        paginator = pages.Paginator(pages=pagess, disable_on_timeout=True, timeout=30, custom_view=SendModalSelect())
        await paginator.respond(interaction, ephemeral=True)
    @discord.ui.button(emoji='🔀', row=1, style=discord.ButtonStyle.primary)
    async def shufflee_button(self, button, interaction: discord.Interaction):
        global queue
        embed = await vc_check(interaction.user, interaction.guild.voice_client)
        if embed != 0:
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        if queue[interaction.guild_id] == []:
            emb = Embed(title=f"Очередь пуста", color=0xe74c3c, timestamp=interaction.message.created_at)

            await interaction.response.send_message(embed=emb, ephemeral=True)
        else:
            random.shuffle(queue[interaction.guild_id])
            emb = Embed(title=f"Очередь перемешена", color=0xe74c3c, timestamp=interaction.message.created_at)

            await interaction.response.send_message(embed=emb)
class SendMlDelQe(discord.ui.View):
    @discord.ui.button(label="Ввести номер", emoji='✅', row=1, style=discord.ButtonStyle.primary)
    async def send_modal_queue(self, button, interaction):
        await interaction.response.send_modal(QueueDelSearch(title="Удаление композиции"))
class QueueDelSearch(discord.ui.Modal):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.add_item(discord.ui.InputText(label="Порядковый номер", style=discord.InputTextStyle.long))
        self.avatar = "https://yt3.ggpht.com/ytc/AKedOLQPLgvRGHtuxEazcF7UXJRJe7WmpToMlnygCfLt=s900-c-k-c0x00ffffff-no-rj"
    async def callback(self, interaction: discord.Interaction):
        global queue
        try:
            deleted = queue[interaction.guild.id].pop(int(self.children[0].value) - 1)
            emb = Embed(description=f"Композиция [{' & '.join([x.name for x in deleted['data'].artists]) + ' - ' + deleted['data'].title}]({deleted['url']}) под номером **{self.children[0].value}** удалена из очереди", color=0xe74c3c)
            await interaction.response.send_message(embed=emb)
        except Exception as e:
            print(e)
            await interaction.response.send_message(embed=Embed(description=f"**Вы ввели неверное число**", color=0xe74c3c), view=None, ephemeral=True)
class ActionRow(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)
    @discord.ui.button(emoji='⬅️', row=0, style=discord.ButtonStyle.primary)
    async def move_left(self, button, interaction):
        global queue
        embed_from = interaction.message.embeds[0]
        position = int(embed_from.fields[1].value)
        if position == 1:
            await interaction.response.send_message(
                embed=Embed(description=f"**Вы не можете сдвинуть композицию еще левее!**", color=0xe74c3c),
                ephemeral=True)
            return
        req = queue[interaction.guild_id].pop(position - 1)
        queue[interaction.guild_id].insert(position - 1 - 1, req)
        emb = Embed(title="Выбранная композиция из очереди", url=embed_from.url, description=embed_from.description,
                    timestamp=interaction.message.created_at, color=0xe74c3c)
        emb.add_field(name="Длительность", value=embed_from.fields[0].value, inline=False)
        emb.add_field(name="Позиция в очереди", value=position - 1, inline=False)
        emb.set_thumbnail(url=embed_from.thumbnail.url)
        emb.set_footer(text=f"Нажимайте на кнопки ниже для взаимодействия.")
        await interaction.response.edit_message(embed=emb, view=self)



    @discord.ui.button(emoji='🗑️', row=0, style=discord.ButtonStyle.primary)
    async def delete(self, button, interaction):
        global queue
        embed_from = interaction.message.embeds[0]
        position = int(embed_from.fields[1].value)
        deleted = queue[interaction.guild_id].pop(position - 1)[0]
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            embed=Embed(description="*Композиция более недоступна!*", timestamp=interaction.message.created_at,
                        color=0xe74c3c), view=self)
        await interaction.followup.send(embed=Embed(description=f"**{interaction.user.name} удалил [{deleted.title}]({deleted.uri}) из очереди**", color=0xe74c3c))
    @discord.ui.button(emoji='❌', row=0, style=discord.ButtonStyle.primary)
    async def exit(self, button, interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji='🔄', row=0, style=discord.ButtonStyle.primary)
    async def change(self, button, interaction):
        await interaction.response.send_modal(Change_Track(title="Смена трека"))

    @discord.ui.button(emoji='➡️', row=0, style=discord.ButtonStyle.primary)
    async def move_right(self, button, interaction):
        global queue
        embed_from = interaction.message.embeds[0]
        position = int(embed_from.fields[1].value)
        if position + 1 > len(queue[interaction.guild_id]):
            await interaction.response.send_message(
                embed=Embed(description=f"**Вы не можете сдвинуть композицию еще правее!**", color=0xe74c3c),
                ephemeral=True)
            return
        req = queue[interaction.guild_id].pop(position - 1)
        queue[interaction.guild_id].insert(position, req)
        emb = Embed(title="Выбранная композиция из очереди", url=embed_from.url, description=embed_from.description,
                    timestamp=interaction.message.created_at, color=0xe74c3c)
        emb.add_field(name="Длительность", value=embed_from.fields[0].value, inline=False)
        emb.add_field(name="Позиция в очереди", value=position + 1, inline=False)
        emb.set_thumbnail(url=embed_from.thumbnail.url)
        emb.set_footer(text=f"Нажимайте на кнопки ниже для взаимодействия.")
        await interaction.response.edit_message(embed=emb, view=self)
class Change_Track(discord.ui.Modal):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.add_item(discord.ui.InputText(label="Введите имя или ссылку на трек", style=discord.InputTextStyle.long))

    async def callback(self, interaction):
        global queue
        embed_from = interaction.message.embeds[0]
        position = int(embed_from.fields[1].value)
        queue[interaction.guild_id].pop(position - 1) # [videosSearch, duration, thumb, link]
        requests = self.children[0].value
        if 'music.yandex.ru' not in requests:
            async with httpx.AsyncClient() as client:
                session = await api.setup_session(session=client, session_id=session_id, user_agent=DEFAULT_USER_AGENT)
                url = await api.get_track_by_name(session, requests)
                track = {"album_id": url.split("track/")[-1], "id":  url.split('album/')[-1].split('/track')[0]}
                session = await api.setup_session(session=client, session_id=session_id, user_agent=DEFAULT_USER_AGENT)
                data = await api.get_full_track_info(session, track_id=track['album_id']) 
                queue[interaction.guild.id].insert(position - 1 , {'url': url ,'data' :data, 'stream': await api.get_track_download_url(session=session, track=track, hq=True), 'author': interaction.user})
        else:
            track = {"album_id": requests.split("track/")[-1], "id":  requests.split('album/')[-1].split('/track')[0]}
            async with httpx.AsyncClient() as client:
                session = await api.setup_session(session=client, session_id=session_id, user_agent=DEFAULT_USER_AGENT)
                data = await api.get_full_track_info(session, track_id=track['album_id']) 
                url = requests
                queue[interaction.guild.id].insert(position - 1, {'url': requests, 'data' :data, 'stream': await api.get_track_download_url(session=session, track=track, hq=True), 'author': interaction.user})
                
        link = url
        thumb = data.cover_info.cover_url_template[:-2:] + 'm400x400'
        title = ' & '.join([x.name for x in data.artists]) + " - " + data.title
        duration = (datetime.timedelta(seconds=data.duration // 1000))
        
        emb = Embed(title="Выбранная композиция из очереди", url=link, description=title, color=0x2ecc71)
        emb.add_field(name="Длительность", value=duration, inline=False)
        emb.add_field(name="Позиция в очереди", value=position, inline=False)
        emb.set_thumbnail(url=thumb)
        emb.set_footer(text=f"Нажимайте на кнопки ниже для взаимодействия.")
        await interaction.response.edit_message(embed=emb, view=ActionRow())
        await interaction.followup.send(embed=Embed(
            description=f"{interaction.user.mention} сменил [{embed_from.description}]({embed_from.url}) на [{title}]({link})",
            color=0x2ecc71))
class QueueSelect(discord.ui.Modal):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.add_item(discord.ui.InputText(label="Введите порядковый номер", style=discord.InputTextStyle.long))
    async def callback(self, interaction: discord.Interaction):
        global queue
        pos = self.children[0].value
        try:
            request = queue[interaction.guild.id][int(pos) - 1]
        except:
            await interaction.response.send_message(f"Произошла некая ошибка! Перепроверьте ваш ввод.", ephemeral=True)
            return
        track = request
        link = track['url']
        thumb = track['data'].cover_info.cover_url_template[:-2:] + 'm400x400'
        title = track['data'].title
        duration = (datetime.timedelta(seconds=int(track['data'].duration) // 1000))
        emb = Embed(title="Выбранная композиция из очереди", url=link, description=title, color=0xe74c3c)
        emb.add_field(name="Длительность", value=duration, inline=False)
        emb.add_field(name="Позиция в очереди", value=int(pos), inline=False)
        emb.set_thumbnail(url=thumb)
        emb.set_footer(text=f"Нажимайте на кнопки ниже для взаимодействия.")
        await interaction.response.send_message(embed=emb, ephemeral=True, view=ActionRow())
        
class QueueInsert(discord.ui.Modal):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.add_item(discord.ui.InputText(label="Введите название трека", style=discord.InputTextStyle.long))
        self.add_item(discord.ui.InputText(label="Введите номер трека"))

    async def callback(self, interaction: discord.Interaction):

        vc = interaction.guild.voice_client
        try:
            requests = self.children[0].value
            index = self.children[1].value
            if 'music.yandex.ru' not in requests:
                async with httpx.AsyncClient() as client:
                    session = await api.setup_session(session=client, session_id=session_id, user_agent=DEFAULT_USER_AGENT)
                    url = await api.get_track_by_name(session, requests)
                    track = {"album_id": url.split("track/")[-1], "id":  url.split('album/')[-1].split('/track')[0]}
                    session = await api.setup_session(session=client, session_id=session_id, user_agent=DEFAULT_USER_AGENT)
                    data = await api.get_full_track_info(session, track_id=track['album_id']) 
                    queue[interaction.guild.id].insert(int(index) - 1, {'url': url ,'data' :data, 'stream': await api.get_track_download_url(session=session, track=track, hq=True), 'author': interaction.user})
            else:
                track = {"album_id": requests.split("track/")[-1], "id":  requests.split('album/')[-1].split('/track')[0]}
                async with httpx.AsyncClient() as client:
                    session = await api.setup_session(session=client, session_id=session_id, user_agent=DEFAULT_USER_AGENT)
                    data = await api.get_full_track_info(session, track_id=track['album_id']) 
                    url = requests
                    queue[interaction.guild.id].insert(int(index) - 1, {'url': requests, 'data' :data, 'stream': await api.get_track_download_url(session=session, track=track, hq=True), 'author': interaction.user})
                    
            emb = Embed(description=f"**[{' & '.join([x.name for x in data.artists]) + ' - ' + data.title}]({url}) была поставлена в очередь под номером {index}**", color=0x0c0c0c)

            await interaction.response.send_message(embed=emb)
        except Exception as e:
            print(e)
            emb = Embed(description=f'**Произошла ошибка в постановке**', color=0x0c0c0c)
            await interaction.response.send_message(embed=emb, ephemeral=True)
class QueueClear(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=20)

    @discord.ui.button(emoji='✅', row=0, style=discord.ButtonStyle.primary)
    async def accept(self, button, interaction):
        global queue
        queue[interaction.guild_id] = []
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            embed=Embed(description=f"**Очередь очищена пользователем {interaction.user.name}**", color=0xe74c3c))

    @discord.ui.button(emoji='❌', row=0, style=discord.ButtonStyle.primary)
    async def decline(self, button, interaction):
        global queue
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=Embed(description=f"**Действие отменено!**", color=0xe74c3c),
                                                view=self)

def setup(bot):
    bot.add_cog(YandexMusic(bot))