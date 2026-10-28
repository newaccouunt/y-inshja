"""
YouTube Downloader Telegram Bot — Advanced UI (FULL FIXED)
Single File | aiogram 3 + yt-dlp | Render-ready
"""

import asyncio, os, re, time, logging, json, hashlib, secrets, threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import aiohttp
import yt_dlp
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, FSInputFile,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ChatAction, ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ═══════════════════════════════════════════════════
#  ⚙️  CONFIG
# ═══════════════════════════════════════════════════
load_dotenv()

BOT_TOKEN    = os.getenv("BOT_TOKEN", "8155390586:AAE0KRnUYtdPaO46WxEsr7EcE4CjstHqni4")
ADMIN_ID     = int(os.getenv("ADMIN_ID", "6840524720"))
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

YTULTRA_API   = "https://api.ytultra.com/ikool/youtube/download"
YTULTRA_MERGE = "https://api.ytultra.com/ikool/media/download/merge"
YTULTRA_SALT  = os.getenv("YTULTRA_SALT", "ytultra_salt_placeholder")

HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36",
    "Content-Type": "application/json",
    "lang": "en",
    "x-app-id": "2",
    "origin": "https://www.ytultra.com",
    "referer": "https://www.ytultra.com/",
    "sec-fetch-site": "same-site",
    "sec-fetch-mode": "cors",
    "sec-ch-ua-platform": '"Android"',
    "sec-ch-ua-mobile": "?1",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("ytbot")

router = Router()
START_TIME = time.time()

# ═══════════════════════════════════════════════════
#  🌐  DUMMY HTTP SERVER (for Render port binding)
# ═══════════════════════════════════════════════════
class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive OK")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()
    def log_message(self, *args):
        pass

def start_health_server():
    port = int(os.getenv("PORT", "8080"))
    try:
        srv = HTTPServer(("0.0.0.0", port), _HealthHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        log.info(f"🌐 Health server on port {port}")
    except Exception as e:
        log.warning(f"Health server failed: {e}")

# ═══════════════════════════════════════════════════
#  🧠  FSM STATES
# ═══════════════════════════════════════════════════
class S(StatesGroup):
    wait_video_url = State()
    wait_audio_url = State()

# ═══════════════════════════════════════════════════
#  🔗  UTILS
# ═══════════════════════════════════════════════════
YT_REGEX = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|shorts/|embed/|v/))([\w-]{11})"
)

def vid_id(url: str):
    m = YT_REGEX.search(url or "")
    return m.group(1) if m else None

def human_size(b: float) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if b < 1024: return f"{b:.1f}{u}"
        b /= 1024
    return f"{b:.1f}TB"

def fmt_dur(s) -> str:
    s = int(s or 0)
    h, r = divmod(s, 3600); m, sec = divmod(r, 60)
    return f"{h}h {m}m {sec}s" if h else f"{m}m {sec}s"

# ═══════════════════════════════════════════════════
#  🌐  YTULTRA API (optional engine)
# ═══════════════════════════════════════════════════
def _nonce(): return secrets.token_hex(16)
def _ts():    return str(int(time.time() * 1000))
def _sign(ts, nonce):
    return hashlib.sha256(f"{nonce}{ts}{YTULTRA_SALT}".encode()).hexdigest()

async def ytultra_fetch(url: str) -> dict:
    ts, nonce = _ts(), _nonce()
    h = {**HEADERS_BASE,
         "timestamp": ts, "nonce": nonce, "sign": _sign(ts, nonce),
         "pragma": "no-cache", "cache-control": "no-cache"}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25)) as s:
            async with s.post(YTULTRA_API, json={"url": url}, headers=h) as r:
                return await r.json(content_type=None)
    except Exception as e:
        return {"error": str(e)}

# ═══════════════════════════════════════════════════
#  ⬇️  YT-DLP ENGINE
# ═══════════════════════════════════════════════════
def _vopts(q: str) -> dict:
    fmt = (f"bestvideo[height<={q}][ext=mp4]+bestaudio[ext=m4a]/"
           f"bestvideo[height<={q}]+bestaudio/best[height<={q}]/best"
           ) if q.isdigit() else "bestvideo+bestaudio/best"
    return {
        "format": fmt,
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s_%(height)s.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "concurrent_fragment_downloads": 4,
        "retries": 3,
        "nocheckcertificate": True,
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }

async def dl_video(url: str, q: str) -> dict:
    loop = asyncio.get_event_loop()
    def _run():
        with yt_dlp.YoutubeDL(_vopts(q)) as y:
            info = y.extract_info(url, download=True)
            path = y.prepare_filename(info)
            if not path.endswith(".mp4"):
                base = path.rsplit(".", 1)[0]
                if os.path.exists(base + ".mp4"): path = base + ".mp4"
            return {
                "file": path,
                "title": info.get("title", "video"),
                "duration": info.get("duration", 0),
                "thumb": info.get("thumbnail"),
                "uploader": info.get("uploader", ""),
            }
    return await loop.run_in_executor(None, _run)

async def dl_audio(url: str, bitrate: str = "192") -> dict:
    loop = asyncio.get_event_loop()
    def _run():
        opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": bitrate,
            }],
            "quiet": True, "no_warnings": True, "noplaylist": True,
            "nocheckcertificate": True,
        }
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=True)
            return {
                "file": os.path.join(DOWNLOAD_DIR, f"{info['id']}.mp3"),
                "title": info.get("title", "audio"),
                "duration": info.get("duration", 0),
                "uploader": info.get("uploader", ""),
            }
    return await loop.run_in_executor(None, _run)

# ═══════════════════════════════════════════════════
#  🎨  KEYBOARDS
# ═══════════════════════════════════════════════════
def kb_main():
    b = InlineKeyboardBuilder()
    b.button(text="🎬 Video Download", callback_data="mode_video")
    b.button(text="🎵 Audio (MP3)",    callback_data="mode_audio")
    b.button(text="ℹ️ Help",           callback_data="help")
    b.button(text="📊 Stats",          callback_data="stats")
    b.adjust(2, 1, 1)
    return b.as_markup()

def kb_quality(vid: str):
    b = InlineKeyboardBuilder()
    for q in ["144", "240", "360", "480", "720", "1080", "1440", "2160"]:
        b.button(text=f"📹 {q}p", callback_data=f"dl:{vid}:{q}")
    b.button(text="⬅️ Back", callback_data="back_main")
    b.adjust(3, 3, 2, 1)
    return b.as_markup()

def kb_audio(vid: str):
    b = InlineKeyboardBuilder()
    b.button(text="🎧 128 kbps", callback_data=f"au:{vid}:128")
    b.button(text="🎧 192 kbps", callback_data=f"au:{vid}:192")
    b.button(text="🎧 320 kbps", callback_data=f"au:{vid}:320")
    b.button(text="⬅️ Back",     callback_data="back_main")
    b.adjust(3, 1)
    return b.as_markup()

def kb_back():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back", callback_data="back_main")]
    ])

def kb_cancel(vid: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data=f"cancel:{vid}")]
    ])

# ═══════════════════════════════════════════════════
#  🏠  START
# ═══════════════════════════════════════════════════
@router.message(CommandStart())
async def start(m: Message):
    name = m.from_user.first_name or "User"
    text = (
        f"👋 <b>Hey {name}!</b>\n\n"
        "🚀 <b>YouTube Downloader Bot</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "📥 <b>Features:</b>\n"
        "  🎬 Video — 144p → 2160p (4K)\n"
        "  🎵 Audio — MP3 128/192/320\n"
        "  ⚡ Super Fast • 🎨 Advanced UI\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "👇 <i>Select an option below</i>"
    )
    try:
        await m.answer_photo(
            photo="https://i.imgur.com/4M34hi2.png",
            caption=text, parse_mode=ParseMode.HTML,
            reply_markup=kb_main(),
        )
    except Exception:
        await m.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())

# ═══════════════════════════════════════════════════
#  ℹ️  HELP / STATS / BACK
# ═══════════════════════════════════════════════════
@router.callback_query(F.data == "help")
async def cb_help(c: CallbackQuery):
    txt = (
        "📖 <b>How to use:</b>\n\n"
        "1️⃣ Send a YouTube link\n"
        "2️⃣ Pick <b>Video</b> or <b>Audio</b>\n"
        "3️⃣ Choose quality / bitrate\n"
        "4️⃣ Wait for upload ⏳\n\n"
        "⚙️ <b>Supported URLs:</b>\n"
        "  • youtube.com/watch?v=...\n"
        "  • youtu.be/...\n"
        "  • youtube.com/shorts/..."
    )
    try:
        await c.message.edit_caption(caption=txt, parse_mode=ParseMode.HTML, reply_markup=kb_back())
    except Exception:
        await c.message.edit_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb_back())
    await c.answer()

@router.callback_query(F.data == "stats")
async def cb_stats(c: CallbackQuery):
    up = int(time.time() - START_TIME)
    h, r = divmod(up, 3600); mnt, s = divmod(r, 60)
    txt = (
        "📊 <b>Bot Stats</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"⏱ Uptime: <b>{h}h {mnt}m {s}s</b>\n"
        f"📁 Files:  <b>{len(os.listdir(DOWNLOAD_DIR))}</b>\n"
        "🟢 Status: <b>Online</b>"
    )
    try:
        await c.message.edit_caption(caption=txt, parse_mode=ParseMode.HTML, reply_markup=kb_back())
    except Exception:
        await c.message.edit_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb_back())
    await c.answer()

@router.callback_query(F.data == "back_main")
async def cb_back(c: CallbackQuery, state: FSMContext):
    await state.clear()
    txt = "👇 <i>Select an option below</i>"
    try:
        await c.message.edit_caption(caption=txt, parse_mode=ParseMode.HTML, reply_markup=kb_main())
    except Exception:
        await c.message.edit_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb_main())
    await c.answer()

# ═══════════════════════════════════════════════════
#  🎬 / 🎵  MODE
# ═══════════════════════════════════════════════════
@router.callback_query(F.data == "mode_video")
async def cb_mode_video(c: CallbackQuery, state: FSMContext):
    await state.set_state(S.wait_video_url)
    txt = "🎬 <b>Video Mode</b>\n\n🔗 <i>Send YouTube URL:</i>"
    try:
        await c.message.edit_caption(caption=txt, parse_mode=ParseMode.HTML, reply_markup=kb_back())
    except Exception:
        await c.message.edit_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb_back())
    await c.answer()

@router.callback_query(F.data == "mode_audio")
async def cb_mode_audio(c: CallbackQuery, state: FSMContext):
    await state.set_state(S.wait_audio_url)
    txt = "🎵 <b>Audio Mode</b>\n\n🔗 <i>Send YouTube URL:</i>"
    try:
        await c.message.edit_caption(caption=txt, parse_mode=ParseMode.HTML, reply_markup=kb_back())
    except Exception:
        await c.message.edit_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb_back())
    await c.answer()

# ═══════════════════════════════════════════════════
#  🔗  RECEIVE URL (FIXED: send_chat_action)
# ═══════════════════════════════════════════════════
@router.message(S.wait_video_url)
async def on_url_video(m: Message, state: FSMContext):
    vid = vid_id(m.text or "")
    if not vid:
        return await m.reply(
            "❌ <b>Invalid YouTube link!</b>\nTry: <code>https://youtu.be/xxxxx</code>",
            parse_mode=ParseMode.HTML,
        )
    await state.clear()
    # ✅ FIX: bot.send_chat_action (not m.answer_chat_action)
    try:
        await m.bot.send_chat_action(chat_id=m.chat.id, action=ChatAction.TYPING)
    except Exception:
        pass
    await m.reply(
        f"🎬 <b>Video Selected</b>\n🆔 <code>{vid}</code>\n\n👇 <i>Choose quality:</i>",
        parse_mode=ParseMode.HTML, reply_markup=kb_quality(vid),
    )

@router.message(S.wait_audio_url)
async def on_url_audio(m: Message, state: FSMContext):
    vid = vid_id(m.text or "")
    if not vid:
        return await m.reply(
            "❌ <b>Invalid YouTube link!</b>",
            parse_mode=ParseMode.HTML,
        )
    await state.clear()
    # ✅ FIX: bot.send_chat_action
    try:
        await m.bot.send_chat_action(chat_id=m.chat.id, action=ChatAction.TYPING)
    except Exception:
        pass
    await m.reply(
        f"🎵 <b>Audio Selected</b>\n🆔 <code>{vid}</code>\n\n👇 <i>Choose bitrate:</i>",
        parse_mode=ParseMode.HTML, reply_markup=kb_audio(vid),
    )

# ═══════════════════════════════════════════════════
#  ⬇️  DOWNLOAD VIDEO
# ═══════════════════════════════════════════════════
@router.callback_query(F.data.startswith("dl:"))
async def cb_dl_video(c: CallbackQuery):
    _, vid, q = c.data.split(":")
    url = f"https://youtube.com/watch?v={vid}"
    await c.answer("⏳ Downloading...")
    try:
        status = await c.message.edit_text(
            f"📥 <b>Downloading {q}p...</b>\n\n"
            f"🆔 <code>{vid}</code>\n"
            "⏳ <i>Please wait...</i>",
            parse_mode=ParseMode.HTML, reply_markup=kb_cancel(vid),
        )
    except Exception:
        status = await c.message.answer(
            f"📥 <b>Downloading {q}p...</b>",
            parse_mode=ParseMode.HTML, reply_markup=kb_cancel(vid),
        )
    try:
        await c.bot.send_chat_action(chat_id=c.message.chat.id, action=ChatAction.UPLOAD_VIDEO)
    except Exception:
        pass

    try:
        info = await dl_video(url, q)
        file = info["file"]
        size = os.path.getsize(file)

        try:
            await status.edit_text(
                f"📤 <b>Uploading...</b>\n\n"
                f"🎬 <b>{info['title'][:60]}</b>\n"
                f"📦 <code>{human_size(size)}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

        await c.message.bot.send_video(
            chat_id=c.message.chat.id,
            video=FSInputFile(file),
            caption=(
                "✅ <b>Download Complete!</b>\n"
                "━━━━━━━━━━━━━━━━\n"
                f"🎬 <b>{info['title'][:60]}</b>\n"
                f"👤 {info['uploader']}\n"
                f"📹 Quality: <b>{q}p</b>\n"
                f"📦 Size: <b>{human_size(size)}</b>\n"
                f"⏱ Duration: <b>{fmt_dur(info['duration'])}</b>"
            ),
            parse_mode=ParseMode.HTML,
            supports_streaming=True,
        )
        try: await status.delete()
        except Exception: pass
        try: os.remove(file)
        except Exception: pass
    except Exception as e:
        log.exception("Video download failed")
        err = str(e)[:220]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Retry", callback_data=f"dl:{vid}:{q}")],
            [InlineKeyboardButton(text="🏠 Menu",  callback_data="back_main")],
        ])
        try:
            await status.edit_text(
                f"❌ <b>Download Failed</b>\n\n<code>{err}</code>",
                parse_mode=ParseMode.HTML, reply_markup=kb,
            )
        except Exception:
            await c.message.answer(
                f"❌ <b>Download Failed</b>\n\n<code>{err}</code>",
                parse_mode=ParseMode.HTML, reply_markup=kb,
            )

# ═══════════════════════════════════════════════════
#  🎵  DOWNLOAD AUDIO
# ═══════════════════════════════════════════════════
@router.callback_query(F.data.startswith("au:"))
async def cb_dl_audio(c: CallbackQuery):
    _, vid, br = c.data.split(":")
    url = f"https://youtube.com/watch?v={vid}"
    await c.answer("🎵 Downloading audio...")
    try:
        status = await c.message.edit_text(
            f"🎵 <b>Downloading MP3 {br}kbps...</b>\n\n⏳ <i>Please wait...</i>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        status = await c.message.answer(
            f"🎵 <b>Downloading MP3 {br}kbps...</b>",
            parse_mode=ParseMode.HTML,
        )
    try:
        await c.bot.send_chat_action(chat_id=c.message.chat.id, action=ChatAction.UPLOAD_VOICE)
    except Exception:
        pass

    try:
        info = await dl_audio(url, br)
        file = info["file"]
        size = os.path.getsize(file)

        await c.message.bot.send_audio(
            chat_id=c.message.chat.id,
            audio=FSInputFile(file),
            caption=(
                "✅ <b>Audio Ready!</b>\n"
                "━━━━━━━━━━━━━━━━\n"
                f"🎵 <b>{info['title'][:60]}</b>\n"
                f"👤 {info['uploader']}\n"
                f"🎧 Bitrate: <b>{br}kbps</b>\n"
                f"📦 Size: <b>{human_size(size)}</b>\n"
                f"⏱ Duration: <b>{fmt_dur(info['duration'])}</b>"
            ),
            parse_mode=ParseMode.HTML,
        )
        try: await status.delete()
        except Exception: pass
        try: os.remove(file)
        except Exception: pass
    except Exception as e:
        log.exception("Audio download failed")
        err = str(e)[:220]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Menu", callback_data="back_main")]
        ])
        try:
            await status.edit_text(
                f"❌ <b>Audio Failed</b>\n\n<code>{err}</code>",
                parse_mode=ParseMode.HTML, reply_markup=kb,
            )
        except Exception:
            await c.message.answer(
                f"❌ <b>Audio Failed</b>\n\n<code>{err}</code>",
                parse_mode=ParseMode.HTML, reply_markup=kb,
            )

# ═══════════════════════════════════════════════════
#  ❌  CANCEL
# ═══════════════════════════════════════════════════
@router.callback_query(F.data.startswith("cancel:"))
async def cb_cancel(c: CallbackQuery):
    await c.answer("❌ Cancelled", show_alert=True)
    try:
        await c.message.edit_text(
            "❌ <b>Cancelled.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Menu", callback_data="back_main")]
            ]),
        )
    except Exception:
        pass

# ═══════════════════════════════════════════════════
#  🔗  AUTO-DETECT LINKS (fallback)
# ═══════════════════════════════════════════════════
@router.message(F.text.regexp(YT_REGEX))
async def any_link(m: Message):
    vid = vid_id(m.text)
    if not vid:
        return
    await m.reply(
        f"🔗 <b>Link Detected!</b>\n🆔 <code>{vid}</code>\n\n👇 <i>Choose format:</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎬 Video", callback_data=f"pickv:{vid}")],
            [InlineKeyboardButton(text="🎵 Audio", callback_data=f"picka:{vid}")],
        ]),
    )

@router.callback_query(F.data.startswith("pickv:"))
async def cb_pick_v(c: CallbackQuery):
    vid = c.data.split(":")[1]
    try:
        await c.message.edit_text(
            f"🎬 <b>Video</b> — <code>{vid}</code>\n\n👇 <i>Choose quality:</i>",
            parse_mode=ParseMode.HTML, reply_markup=kb_quality(vid),
        )
    except Exception:
        await c.message.answer(
            f"🎬 <b>Video</b> — <code>{vid}</code>\n\n👇 <i>Choose quality:</i>",
            parse_mode=ParseMode.HTML, reply_markup=kb_quality(vid),
        )
    await c.answer()

@router.callback_query(F.data.startswith("picka:"))
async def cb_pick_a(c: CallbackQuery):
    vid = c.data.split(":")[1]
    try:
        await c.message.edit_text(
            f"🎵 <b>Audio</b> — <code>{vid}</code>\n\n👇 <i>Choose bitrate:</i>",
            parse_mode=ParseMode.HTML, reply_markup=kb_audio(vid),
        )
    except Exception:
        await c.message.answer(
            f"🎵 <b>Audio</b> — <code>{vid}</code>\n\n👇 <i>Choose bitrate:</i>",
            parse_mode=ParseMode.HTML, reply_markup=kb_audio(vid),
        )
    await c.answer()

# ═══════════════════════════════════════════════════
#  🚀  MAIN
# ═══════════════════════════════════════════════════
async def main():
    start_health_server()  # ✅ Render free plan pe sleep nahi hoga
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    log.info("🚀 Bot starting...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("🛑 Bot stopped")
