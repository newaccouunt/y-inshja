import os
import re
import random
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify
import yt_dlp
import requests

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ============================================================
#                  PROXY MANAGER (LIVE FETCH)
# ============================================================
class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.lock = threading.Lock()
        self.last_refresh = 0
        self.REFRESH_INTERVAL = 1800  # 30 min
        self.alive = set()

    # ---------- Source URLs ----------
    SOURCES = [
        # APIs (TXT)
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
        "https://api.proxyscrape.com/v4/free-proxy-list/get?request=displayproxies&protocol=http&timeout=10000",
        "https://api.proxyscrape.com/?request=displayproxies&proxytype=http",
        "https://www.proxy-list.download/api/v1/get?type=http",
        "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
        "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
        "https://raw.githubusercontent.com/opsxcq/proxy-list/master/list.txt",
        "https://raw.githubusercontent.com/mertguvencli/http-proxy-list/main/proxy-list/data.txt",
        "https://raw.githubusercontent.com/almighty-uncle/Proxy-List/main/HTTP.txt",
        "https://raw.githubusercontent.com/proxy-free/free-proxy-list/main/proxies/http.txt",
        "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
        # JSON APIs
        "https://api.proxifly.dev/proxy?protocol=http&limit=50",
        "https://api.getproxylist.com/proxy?protocol=http",
        # HTML pages
        "https://free-proxy-list.net/",
        "https://www.sslproxies.org/",
        "https://www.us-proxy.org/",
        "https://www.socks-proxy.net/",
    ]

    IP_REGEX = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}:\d+\b")

    def fetch_one(self, url):
        try:
            r = requests.get(url, timeout=6, verify=False, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            if r.status_code != 200 or not r.text:
                return []
            text = r.text

            # HTML?
            if "<html" in text.lower() or "<body" in text.lower():
                found = self.IP_REGEX.findall(text)
                return [self._clean(p) for p in found]

            # JSON?
            try:
                data = r.json()
                out = []
                if isinstance(data, dict):
                    if "proxy" in data and isinstance(data["proxy"], str):
                        out.append(data["proxy"])
                    if "data" in data and isinstance(data["data"], list):
                        for item in data["data"]:
                            if isinstance(item, dict) and item.get("ip") and item.get("port"):
                                out.append(f"{item['ip']}:{item['port']}")
                    if "proxies" in data and isinstance(data["proxies"], list):
                        out.extend([str(x) for x in data["proxies"]])
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("ip") and item.get("port"):
                            out.append(f"{item['ip']}:{item['port']}")
                        elif isinstance(item, str):
                            out.append(item)
                return [self._clean(p) for p in out]
            except Exception:
                pass

            # Plain TXT
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            return [self._clean(l) for l in lines if ":" in l]
        except Exception as e:
            logging.debug(f"fetch {url} err: {e}")
            return []

    def _clean(self, p):
        m = re.match(r"^(?:https?://)?(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{1,5})", p)
        return f"{m.group(1)}:{m.group(2)}" if m else None

    def refresh(self):
        logging.info("Refreshing proxy list...")
        found = set()
        with ThreadPoolExecutor(max_workers=20) as ex:
            futures = [ex.submit(self.fetch_one, u) for u in self.SOURCES]
            for f in as_completed(futures):
                for p in f.result():
                    if p:
                        found.add(p)

        # secret file + env var
        for path in ["/etc/secrets/proxies.txt", "proxies.txt"]:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        c = self._clean(line.strip())
                        if c:
                            found.add(c)
        envp = os.environ.get("PROXIES", "")
        if envp:
            for p in envp.split(","):
                c = self._clean(p.strip())
                if c:
                    found.add(c)

        with self.lock:
            self.proxies = list(found)
            self.last_refresh = time.time()
        logging.info(f"Proxy pool refreshed: {len(self.proxies)} total")

    def get(self):
        if time.time() - self.last_refresh > self.REFRESH_INTERVAL or not self.proxies:
            try:
                self.refresh()
            except Exception as e:
                logging.error(f"refresh fail: {e}")
        with self.lock:
            if not self.proxies:
                return None
            return random.choice(self.proxies)

    def count(self):
        return len(self.proxies)


PM = ProxyManager()
try:
    PM.refresh()
except Exception as e:
    logging.error(f"Initial proxy refresh failed: {e}")


def proxy_url(p):
    return f"http://{p}" if p else None


# ============================================================
#                    URL DETECTION
# ============================================================
def is_youtube(url):
    return bool(re.match(r"^(https?://)?(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/", url, re.I))

def is_youtube_music(url):
    return bool(re.match(r"^(https?://)?music\.youtube\.com/", url, re.I))

def is_facebook(url):
    return bool(re.match(r"^(https?://)?(www\.|m\.|web\.)?(facebook\.com|fb\.watch|fb\.me)/", url, re.I))

def is_instagram(url):
    return bool(re.match(r"^(https?://)?(www\.)?instagram\.com/", url, re.I))


# ============================================================
#                    YT-DLP CORE
# ============================================================
QUALITY_MAP = {
    "144p":  ("worstvideo[height<=144]+worstaudio/worst[height<=144]", 144),
    "240p":  ("bestvideo[height<=240]+bestaudio/best[height<=240]", 240),
    "360p":  ("bestvideo[height<=360]+bestaudio/best[height<=360]", 360),
    "480p":  ("bestvideo[height<=480]+bestaudio/best[height<=480]", 480),
    "720p":  ("bestvideo[height<=720]+bestaudio/best[height<=720]", 720),
    "1080p": ("bestvideo[height<=1080]+bestaudio/best[height<=1080]", 1080),
    "1440p": ("bestvideo[height<=1440]+bestaudio/best[height<=1440]", 1440),
    "2160p": ("bestvideo[height<=2160]+bestaudio/best[height<=2160]", 2160),
    "best":  ("bestvideo+bestaudio/best", 99999),
    "audio": ("bestaudio/best", 0),
}

BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "skip_download": True,
    "socket_timeout": 30,
    "retries": 2,
    "geo_bypass": True,
    "nocheckcertificate": True,
    "extractor_args": {
        "youtube": {"player_client": ["android", "ios", "web", "tv"]},
        "youtube:music": {"player_client": ["web", "android"]},
    },
    "http_headers": {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36"
        )
    },
}


def pick_format(formats, max_height, want_audio=False):
    if not formats:
        return None
    if want_audio:
        auds = [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
        if auds:
            return max(auds, key=lambda f: (f.get("abr") or 0, f.get("tbr") or 0))
        return None
    cands = [
        f for f in formats
        if f.get("vcodec") not in (None, "none")
        and f.get("height")
        and f["height"] <= max_height
    ]
    if not cands:
        cands = [f for f in formats if f.get("vcodec") not in (None, "none")]
    return max(cands, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0)) if cands else None


def extract_info_with_retry(url, opts, tries=6):
    """Try random proxies + final no-proxy attempt."""
    used_proxy = None
    last_err = None
    for i in range(tries):
        p = PM.get()
        o = dict(opts)
        if p:
            o["proxy"] = proxy_url(p)
        try:
            with yt_dlp.YoutubeDL(o) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    used_proxy = p
                    return info, used_proxy
        except Exception as e:
            last_err = e
            logging.warning(f"[try {i+1}] proxy={p} err={str(e)[:120]}")
            continue
    # final: direct
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False), None
    except Exception as e:
        raise last_err or e


# ============================================================
#                    ROUTES
# ============================================================
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "ok",
        "proxies_loaded": PM.count(),
        "endpoints": {
            "/yt": "?link=YT_URL&quality=144p|240p|360p|480p|720p|1080p|1440p|2160p|best|audio",
            "/yt/audio": "?link=YT_URL   (audio only)",
            "/ytmusic": "?link=music.youtube.com/...   (audio ya best)",
            "/fb": "?link=FB_VIDEO_OR_REEL",
            "/insta": "?link=INSTAGRAM_REEL",
            "/auto": "?link=ANY&quality=720p",
            "/proxies/refresh": "force refresh proxy list",
        },
    })


# ---------- YouTube video ----------
@app.route("/yt", methods=["GET"])
def yt_route():
    link = request.args.get("link", "").strip()
    quality = request.args.get("quality", "720p").strip().lower()
    if not link:
        return jsonify({"error": "missing link"}), 400
    if not is_youtube(link):
        return jsonify({"error": "not youtube"}), 400
    if quality not in QUALITY_MAP:
        return jsonify({"error": "bad quality", "allowed": list(QUALITY_MAP.keys())}), 400

    fmt, max_h = QUALITY_MAP[quality]
    o = dict(BASE_OPTS)
    o["format"] = fmt

    try:
        info, used = extract_info_with_retry(link, o)
        if info.get("_type") == "playlist":
            entries = info.get("entries") or []
            if not entries:
                return jsonify({"error": "empty playlist"}), 404
            info = entries[0]

        chosen = pick_format(info.get("formats") or [], max_h, want_audio=(quality == "audio"))
        url = (chosen or {}).get("url") or info.get("url")
        if not url:
            return jsonify({"error": "no format"}), 404

        return jsonify({
            "success": True,
            "platform": "youtube" + ("_music" if is_youtube_music(link) else ""),
            "title": info.get("title"),
            "id": info.get("id"),
            "duration_string": info.get("duration_string"),
            "thumbnail": info.get("thumbnail"),
            "uploader": info.get("uploader") or info.get("channel"),
            "artist": info.get("artist"),
            "track": info.get("track"),
            "requested_quality": quality,
            "selected_quality": (
                f"{chosen.get('height')}p" if chosen and chosen.get("height")
                else ("audio" if quality == "audio" else quality)
            ),
            "ext": chosen.get("ext") if chosen else info.get("ext"),
            "filesize": (chosen.get("filesize") or chosen.get("filesize_approx")) if chosen else None,
            "download_url": url,
            "proxy_used": bool(used),
        }), 200
    except Exception as e:
        return jsonify({"error": "ytdlp", "detail": str(e)}), 502


# ---------- YouTube Audio-only ----------
@app.route("/yt/audio", methods=["GET"])
def yt_audio():
    link = request.args.get("link", "").strip()
    if not link:
        return jsonify({"error": "missing link"}), 400
    if not is_youtube(link):
        return jsonify({"error": "not youtube"}), 400

    o = dict(BASE_OPTS)
    o["format"] = "bestaudio/best"

    try:
        info, used = extract_info_with_retry(link, o)
        chosen = pick_format(info.get("formats") or [], 0, want_audio=True)
        url = (chosen or {}).get("url") or info.get("url")
        if not url:
            return jsonify({"error": "no audio"}), 404
        return jsonify({
            "success": True,
            "platform": "youtube_audio",
            "title": info.get("title"),
            "artist": info.get("artist") or info.get("uploader"),
            "duration_string": info.get("duration_string"),
            "thumbnail": info.get("thumbnail"),
            "ext": chosen.get("ext") if chosen else "m4a",
            "abr": chosen.get("abr") if chosen else None,
            "filesize": (chosen.get("filesize") or chosen.get("filesize_approx")) if chosen else None,
            "download_url": url,
            "proxy_used": bool(used),
        }), 200
    except Exception as e:
        return jsonify({"error": "ytdlp", "detail": str(e)}), 502


# ---------- YouTube Music (audio + video) ----------
@app.route("/ytmusic", methods=["GET"])
def ytmusic_route():
    link = request.args.get("link", "").strip()
    quality = request.args.get("quality", "audio").strip().lower()
    if not link:
        return jsonify({"error": "missing link"}), 400
    if not is_youtube_music(link):
        return jsonify({"error": "not youtube music"}), 400
    if quality not in QUALITY_MAP:
        return jsonify({"error": "bad quality", "allowed": list(QUALITY_MAP.keys())}), 400

    fmt, max_h = QUALITY_MAP[quality]
    o = dict(BASE_OPTS)
    o["format"] = fmt

    try:
        info, used = extract_info_with_retry(link, o)
        if info.get("_type") == "playlist":
            entries = info.get("entries") or []
            if not entries:
                return jsonify({"error": "empty playlist"}), 404
            info = entries[0]

        chosen = pick_format(info.get("formats") or [], max_h, want_audio=(quality == "audio"))
        url = (chosen or {}).get("url") or info.get("url")
        if not url:
            return jsonify({"error": "no format"}), 404
        return jsonify({
            "success": True,
            "platform": "youtube_music",
            "title": info.get("track") or info.get("title"),
            "artist": info.get("artist") or info.get("creator") or info.get("uploader"),
            "album": info.get("album"),
            "release_year": info.get("release_year"),
            "duration_string": info.get("duration_string"),
            "thumbnail": info.get("thumbnail"),
            "requested_quality": quality,
            "selected_quality": (
                f"{chosen.get('height')}p" if chosen and chosen.get("height")
                else ("audio" if quality == "audio" else quality)
            ),
            "ext": chosen.get("ext") if chosen else info.get("ext"),
            "download_url": url,
            "proxy_used": bool(used),
        }), 200
    except Exception as e:
        return jsonify({"error": "ytdlp", "detail": str(e)}), 502


# ---------- Facebook ----------
@app.route("/fb", methods=["GET"])
def fb_route():
    link = request.args.get("link", "").strip()
    if not link:
        return jsonify({"error": "missing link"}), 400
    if not is_facebook(link):
        return jsonify({"error": "not facebook"}), 400

    o = dict(BASE_OPTS)
    o["format"] = "bestvideo+bestaudio/best"

    try:
        info, used = extract_info_with_retry(link, o)
        if info.get("_type") == "playlist":
            entries = info.get("entries") or []
            if not entries:
                return jsonify({"error": "empty"}), 404
            info = entries[0]

        # best combined
        formats = info.get("formats") or []
        best = None
        # prefer combined (v+a) progressive
        combined = [f for f in formats if f.get("vcodec") not in (None, "none")
                    and f.get("acodec") not in (None, "none") and f.get("url")]
        if combined:
            best = max(combined, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))
        else:
            vids = [f for f in formats if f.get("vcodec") not in (None, "none") and f.get("url")]
            if vids:
                best = max(vids, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))

        url = (best or {}).get("url") or info.get("url")
        if not url:
            return jsonify({"error": "no format"}), 404

        return jsonify({
            "success": True,
            "platform": "facebook",
            "title": info.get("title") or info.get("description"),
            "id": info.get("id"),
            "duration_string": info.get("duration_string"),
            "thumbnail": info.get("thumbnail"),
            "uploader": info.get("uploader") or info.get("channel"),
            "quality": f"{best.get('height')}p" if best and best.get("height") else "source",
            "ext": best.get("ext") if best else info.get("ext"),
            "filesize": (best.get("filesize") or best.get("filesize_approx")) if best else None,
            "download_url": url,
            "proxy_used": bool(used),
        }), 200
    except Exception as e:
        return jsonify({"error": "ytdlp", "detail": str(e)}), 502


# ---------- Instagram ----------
@app.route("/insta", methods=["GET"])
def insta_route():
    link = request.args.get("link", "").strip()
    if not link:
        return jsonify({"error": "missing link"}), 400
    if not is_instagram(link):
        return jsonify({"error": "not instagram"}), 400

    o = dict(BASE_OPTS)
    o.pop("extractor_args", None)
    o.pop("format", None)

    try:
        info, used = extract_info_with_retry(link, o)
        entries = info.get("entries") or [info]
        media = []
        for e in entries:
            formats = e.get("formats") or []
            vids = [f for f in formats if f.get("vcodec") not in (None, "none") and f.get("url")]
            if vids:
                best = max(vids, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))
                media.append({"type": "video", "url": best["url"], "ext": best.get("ext", "mp4"), "height": best.get("height")})
            elif e.get("url"):
                media.append({"type": "image", "url": e["url"], "ext": "jpg"})
            elif e.get("thumbnail"):
                media.append({"type": "image", "url": e["thumbnail"], "ext": "jpg"})

        if not media:
            return jsonify({"error": "no media"}), 404

        return jsonify({
            "success": True,
            "platform": "instagram",
            "title": info.get("title") or info.get("description"),
            "uploader": info.get("uploader") or info.get("channel"),
            "thumbnail": info.get("thumbnail"),
            "count": len(media),
            "media": media,
            "proxy_used": bool(used),
        }), 200
    except Exception as e:
        return jsonify({"error": "ytdlp", "detail": str(e)}), 502


# ---------- Auto ----------
@app.route("/auto", methods=["GET"])
def auto_route():
    link = request.args.get("link", "").strip()
    if not link:
        return jsonify({"error": "missing link"}), 400
    if is_youtube_music(link):
        return ytmusic_route()
    if is_youtube(link):
        return yt_route()
    if is_facebook(link):
        return fb_route()
    if is_instagram(link):
        return insta_route()
    return jsonify({"error": "unsupported"}), 400


# ---------- Proxy refresh ----------
@app.route("/proxies/refresh", methods=["GET"])
def proxies_refresh():
    PM.refresh()
    return jsonify({"success": True, "count": PM.count()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
