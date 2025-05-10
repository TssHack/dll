from telethon import TelegramClient, events
import aiohttp
import json
import re

api_id = 25790571
api_hash = '2b95fb1f6f630a83e0712e84ddb337f2'
bot_token = '7862521087:AAH3-a402vIKzJl4SrT-n3DbG6b68p6Espk'

bot = TelegramClient('downloader_bot', api_id, api_hash).start(bot_token=bot_token)

‎
async def download_instagram(url):
    api_url = f"http://amirplus.alfahost.space/api/downloader/insta-2.php?url={url}"
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as resp:
            data = await resp.json()
            try:
                video_url = data['video'][0]['video']
                return {'type': 'video', 'url': video_url}
            except:
                return None

async def download_pinterest(url):
    api_url = f"http://amirplus.alfahost.space/api/downloader/pinterest.php?url={url}"
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as resp:
            data = await resp.json()
            try:
                largest = data['thumbnails'][-1]['url']
                return {'type': 'image', 'url': largest}
            except:
                return None

async def download_youtube(url):
    api_url = f"http://amirplus.alfahost.space/api/downloader/yt.php?url={url}"
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as resp:
            data = await resp.json()
            try:
                video_url = data['medias'][0]['resource_url']
                return {'type': 'video', 'url': video_url}
            except:
                return None

‎
@bot.on(events.NewMessage(pattern=r'http.*'))
async def handler(event):
    url = event.raw_text.strip()

    if 'instagram.com' in url:
        result = await download_instagram(url)
    elif 'pinterest.com' in url:
        result = await download_pinterest(url)
    elif 'youtube.com' in url or 'youtu.be' in url:
        result = await download_youtube(url)
    else:
        await event.reply("لینک پشتیبانی نمی‌شود. لطفاً یکی از لینک‌های اینستاگرام، یوتیوب یا پینترست ارسال کنید.")
        return

    if result:
        if result['type'] == 'video':
            await event.reply("در حال ارسال ویدیو...", file=result['url'])
        elif result['type'] == 'image':
            await event.reply("در حال ارسال تصویر...", file=result['url'])
    else:
        await event.reply("متأسفانه دانلود با خطا مواجه شد.")

print("ربات فعال شد...")
bot.run_until_disconnected()
