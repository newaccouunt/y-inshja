import os
import re
from flask import Flask, request, jsonify
import yt_dlp

app = Flask(__name__)

# ---------- Config ----------
QUALITY_MAP = {
    "144p":  ("worstvideo[height<=144]+worstaudio/worst[height<=144]", 144),
    "240p":  ("bestvideo[height<=240]+bestaudio/best[height<=240]", 240),
    "360p":  ("bestvideo[height<=360]+bestaudio/best[height<=360]", 360),
    "480p":  ("bestvideo[height<=480]+bestaudio/best[height<=480]", 480),
    "720p":  ("bestvideo[height<=720]+bestaudio/best[height<=720]", 720),
    "1080p": ("bestvideo[height<=1080]+bestaudio/best[height<=1080]", 1080),
    "best":  ("bestvideo+bestaudio/best", 9999),
    "audio": ("bestaudio/best", 0),
}

YDL_BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "skip_download": True,
    "extract_flat": False,
    "socket_timeout": 30,
    "retries": 3,
    "geo_bypass": True,
    "nocheckcertificate": True,
    # Render ke datacenter IP ke liye better client
    "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    "http_headers": {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36"
        )
    },
}


# ---------- Helpers ----------
def is_valid_url(url: str) -> bool:
    pattern = re.compile(
        r"^(https?://)?(www\.)?"
        r"(youtube\.com|youtu\.be|m\.youtube\.com|music\.youtube\.com)/"
        r".+",
        re.IGNORECASE,
    )
    return bool(pattern.match(url.strip()))


def pick_format(formats, max_height, want_audio=False):
    """Best format chuno jo quality match kare + audio ho."""
    if not formats:
        return None

    if want_audio:
        audio_only = [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") != "none"]
        if audio_only:
            return max(audio_only, key=lambda f: f.get("abr") or 0)
        return None

    # Sirf woh formats jisme video + audio dono ho (progressive) ya video-only
    candidates = [
        f for f in formats
        if f.get("vcodec") not in (None, "none")
        and f.get("height")
        and f["height"] <= max_height
    ]
    if not candidates:
        # fallback: koi bhi best
        candidates = [f for f in formats if f.get("vcodec") not in (None, "none")]

    if not candidates:
        return None

    # Sabse zyada height wala (par max_height ke andar)
    return max(candidates, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))


# ---------- Routes ----------
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "ok",
        "endpoints": {
            "/yt": "?link=YOUTUBE_URL&quality=144p|240p|360p|480p|720p|1080p|best|audio"
        },
        "example": "/yt?link=https://youtu.be/dQw4w9WgXcQ&quality=720p",
    })


@app.route("/yt", methods=["GET"])
def youtube_download():
    link = request.args.get("link", "").strip()
    quality = request.args.get("quality", "720p").strip().lower()

    if not link:
        return jsonify({"error": "Missing 'link' parameter"}), 400
    if not is_valid_url(link):
        return jsonify({"error": "Invalid YouTube URL"}), 400

    if quality not in QUALITY_MAP:
        return jsonify({
            "error": f"Invalid quality '{quality}'",
            "allowed": list(QUALITY_MAP.keys()),
        }), 400

    fmt_str, max_height = QUALITY_MAP[quality]
    ydl_opts = dict(YDL_BASE_OPTS)
    ydl_opts["format"] = fmt_str

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=False)

            # Playlist case (noplaylist=True hone ke baad bhi safety)
            if info.get("_type") == "playlist":
                entries = info.get("entries") or []
                if not entries:
                    return jsonify({"error": "Playlist empty"}), 404
                info = entries[0]

            formats = info.get("formats") or []
            chosen = pick_format(
                formats,
                max_height,
                want_audio=(quality == "audio"),
            )

            # Fallback: yt-dlp ka seedha url
            direct_url = (chosen or {}).get("url") or info.get("url")
            if not direct_url:
                return jsonify({"error": "No downloadable format found"}), 404

            return jsonify({
                "success": True,
                "title": info.get("title"),
                "id": info.get("id"),
                "duration": info.get("duration"),
                "duration_string": info.get("duration_string"),
                "thumbnail": info.get("thumbnail"),
                "uploader": info.get("uploader"),
                "view_count": info.get("view_count"),
                "requested_quality": quality,
                "selected_quality": f"{chosen.get('height')}p" if chosen and chosen.get("height") else chosen.get("format_note", quality) if chosen else quality,
                "ext": chosen.get("ext") if chosen else info.get("ext"),
                "filesize": chosen.get("filesize") or chosen.get("filesize_approx") if chosen else None,
                "download_url": direct_url,
            }), 200

    except yt_dlp.utils.DownloadError as e:
        return jsonify({"error": "DownloadError", "detail": str(e)}), 502
    except Exception as e:
        return jsonify({"error": "ServerError", "detail": str(e)}), 500


# Render ke liye: gunicorn app:app use karega, ye fallback local ke liye
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
