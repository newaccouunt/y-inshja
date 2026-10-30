import os
import re
import logging
from flask import Flask, request, jsonify
import yt_dlp

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ============================================================
#                    URL DETECTION
# ============================================================
def is_youtube(url):
    return bool(re.match(r"^(https?://)?(www\.|m\.)?(youtube\.com|youtu\.be)/", url, re.I))

def is_youtube_music(url):
    return bool(re.match(r"^(https?://)?music\.youtube\.com/", url, re.I))

def is_facebook(url):
    return bool(re.match(r"^(https?://)?(www\.|m\.|web\.)?(facebook\.com|fb\.watch|fb\.me)/", url, re.I))

def is_instagram(url):
    return bool(re.match(r"^(https?://)?(www\.)?instagram\.com/", url, re.I))


# ============================================================
#                    YT-DLP CONFIG
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
    "retries": 3,
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


# ============================================================
#                    HELPERS
# ============================================================
def pick_format(formats, max_height, want_audio=False):
    if not formats:
        return None
    if want_audio:
        auds = [f for f in formats if f.get("vcodec") == "none"
                and f.get("acodec") not in (None, "none")]
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


def extract_info(url, opts):
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info.get("_type") == "playlist":
            entries = info.get("entries") or []
            if not entries:
                raise Exception("Empty playlist")
            info = entries[0]
        return info


# ============================================================
#                    ROUTES
# ============================================================
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "ok",
        "endpoints": {
            "/yt": "?link=YT_URL&quality=144p|240p|360p|480p|720p|1080p|1440p|2160p|best|audio",
            "/yt/audio": "?link=YT_URL  (audio only)",
            "/ytmusic": "?link=music.youtube.com/...&quality=audio|720p|best...",
            "/fb": "?link=FB_VIDEO_OR_REEL",
            "/insta": "?link=INSTAGRAM_REEL",
            "/auto": "?link=ANY_URL&quality=720p",
        },
    })


# ---------- YouTube Video ----------
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
        info = extract_info(link, o)
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
        }), 200
    except Exception as e:
        return jsonify({"error": "ytdlp", "detail": str(e)}), 502


# ---------- YouTube Audio Only ----------
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
        info = extract_info(link, o)
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
        }), 200
    except Exception as e:
        return jsonify({"error": "ytdlp", "detail": str(e)}), 502


# ---------- YouTube Music ----------
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
        info = extract_info(link, o)
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
    o.pop("extractor_args", None)  # FB ke liye youtube args nahi
    o["format"] = "bestvideo+bestaudio/best"

    try:
        info = extract_info(link, o)
        formats = info.get("formats") or []

        # prefer combined video+audio
        combined = [f for f in formats if f.get("vcodec") not in (None, "none")
                    and f.get("acodec") not in (None, "none") and f.get("url")]
        best = None
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
        info = extract_info(link, o)
        entries = info.get("entries") or [info]
        media = []
        for e in entries:
            formats = e.get("formats") or []
            vids = [f for f in formats if f.get("vcodec") not in (None, "none") and f.get("url")]
            if vids:
                best = max(vids, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))
                media.append({"type": "video", "url": best["url"],
                              "ext": best.get("ext", "mp4"),
                              "height": best.get("height")})
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
