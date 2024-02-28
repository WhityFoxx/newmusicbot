
import xml.etree.ElementTree as ET
import hashlib
import urllib.parse
from typing import Optional
from .models import *
import time
DEFAULT_USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/106.0.0.0 Safari/537.36'
MD5_SALT = 'XGRlBW9FXlekgbPrRHuSiA'
session_id = "3:1701405655.5.0.1671970471825:uUmaWg:11.1.2:1|1209436357.0.2.0:3|1719714717.1074245.2.2:1074245|8200298.24454592.2.2:24454592.3:1696425063|3:10279469.370066.Fzq8AyZgmZe_MP-qqrqTuUoCTvs"

async def get_track_download_url(session, track, hq: bool) -> str:
    resp = await session.get('https://music.yandex.ru/api/v2.1/handlers/track'
            f'/{track["album_id"]}:{track["id"]}'
                       '/web-album_track-track-track-main/download/m'
                       f'?hq={int(hq)}')
    url_info_src = resp.json()['src']

    resp = await session.get('https:' + url_info_src)
    url_info = ET.fromstring(resp.text)
    path = url_info.find('path').text[1:]
    s = url_info.find('s').text
    ts = url_info.find('ts').text
    host = url_info.find('host').text
    path_hash = hashlib.md5((MD5_SALT + path + s).encode()).hexdigest()
    return f'https://{host}/get-mp3/{path_hash}/{ts}/{path}?track-id={track["id"]}'
async def get_track_download_url_pe(session, track, hq: bool) -> str:
    resp = await session.get('https://music.yandex.ru/api/v2.1/handlers/track'
                       f'/{track.id}:{track.album.id}'
                       '/web-album_track-track-track-main/download/m'
                       f'?hq={int(hq)}')
    url_info_src = resp.json()['src']

    resp = await session.get('https:' + url_info_src)
    url_info = ET.fromstring(resp.text)
    path = url_info.find('path').text[1:]
    s = url_info.find('s').text
    ts = url_info.find('ts').text
    host = url_info.find('host').text
    path_hash = hashlib.md5((MD5_SALT + path + s).encode()).hexdigest()
    return f'https://{host}/get-mp3/{path_hash}/{ts}/{path}?track-id={track.id}'

async def setup_session(session,
                  session_id: str,
                  user_agent: str,
                  spravka: Optional[str] = None):
    session.cookies.set('Session_id', session_id, domain='yandex.ru')
    if spravka:
        session.cookies.set('spravka', spravka, domain='yandex.ru')
    session.headers['User-Agent'] = user_agent
    session.headers['X-Retpath-Y'] = urllib.parse.quote_plus(
        'https://music.yandex.ru')
    return session

async def get_full_track_info(session, track_id: str) -> FullTrackInfo:
    params = {'track': track_id, 'lang': 'ru'}
    resp = await session.get('https://music.yandex.ru/handlers/track.jsx',
                       params=params)
    data = resp.json()

    return FullTrackInfo.from_json(data)

async def get_track_by_name(session, track_name: str) -> str:
    payload = {'text': track_name, 'type': 'all', 'clientNow': int(time.time()), 'lang': 'ru', 'external-domain' : 'music.yandex.ru', 'overembed' : 'false'}
    resp = await session.get('https://music.yandex.ru/handlers/music-search.jsx', params=payload)
    data = resp.json()
    return f"https://music.yandex.ru/album/{data['tracks']['items'][0]['albums'][0]['id']}/track/{data['tracks']['items'][0]['id']}"

async def get_playlist(session,
                 playlist: PlaylistId) -> list[BasicTrackInfo]:
    
    params = {'owner': playlist.owner, 'kinds': playlist.kind, 'lang': 'ru'}
    resp = await session.get('https://music.yandex.ru/handlers/playlist.jsx',
                       params=params)
                       
    raw_tracks = resp.json()['playlist'].get('tracks', [])
    tracks = map(BasicTrackInfo.from_json, raw_tracks)
    tracks = [t for t in tracks if t is not None]
    return tracks