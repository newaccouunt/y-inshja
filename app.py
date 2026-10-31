import os
import re
import logging
from flask import Flask, request, jsonify
import yt_dlp

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ---------- URL Check ----------
def is_yt(u): return bool(re.match(r"^(https?://)?(www\.|m\.)?(youtube\.com|youtu\.be)/", u, re.I))
def is_fb(u): return bool(re.match(r"^(https?://)?(www\.|m\.|web\.)?(facebook\.com|fb\.watch|fb\.me)/", u, re.I))
def is_ig(u): return bool(re.match(r"^(https?://)?(www\.)?instagram\.com/", u, re.I))

# ---------- yt-dlp Config ----------
QUALITY = {
    "144p": ("worst[height<=144]", 144),
    "360p": ("best[height<=360]", 360),
    "480p": ("best[height<=480]", 480),
    "720p": ("best[height<=720]", 720),
    "1080p": ("best[height<=1080]", 1080),
    "best": ("best", 9999),
    "audio": ("bestaudio/best", 0),
}

# Render ke liye base options
BASE["extractor_args"] = {
    "youtube": {
        "player_client": ["mweb"],
        "po_token": ["mweb+web:http://bgutil-provider:4416"],
    },
}

# Cookies file path (Render par /etc/secrets/ mein rakhna hoga)
COOKIE_PATH = "/etc/secrets/cookies.txt"

def get_opts(quality="720p"):
    fmt, _ = QUALITY.get(quality, QUALITY["720p"])
    opts = dict(BASE)
    opts["format"] = fmt
    # Agar cookies file exist karti hai, toh use karo
    if os.path.exists(COOKIE_PATH):
        opts["cookiefile"] = COOKIE_PATH
        logging.info("Using cookies.txt")
    else:
        logging.warning("cookies.txt not found, trying without cookies")
    return opts

def extract(url, opts):
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=False)
        if info.get("_type") == "playlist":
            info = (info.get("entries") or [None])[0]
        return info

# ---------- Routes ----------
@app.route("/")
def home():
    return jsonify({"status": "ok", "note": "Render deployment with cookies"})

@app.route("/yt")
def yt():
    link = request.args.get("link", "").strip()
    q = request.args.get("quality", "720p").lower()
    if not link or not is_yt(link):
        return jsonify({"error": "invalid link"}), 400
    
    try:
        info = extract(link, get_opts(q))
        url = info.get("url")
        if not url and info.get("formats"):
            url = info["formats"][-1]["url"]
        return jsonify({
            "success": True,
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration_string"),
            "download_url": url
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502

@app.route("/fb")
def fb():
    link = request.args.get("link", "").strip()
    if not link or not is_fb(link):
        return jsonify({"error": "invalid link"}), 400
    try:
        info = extract(link, get_opts("best"))
        url = info.get("url") or info["formats"][-1]["url"]
        return jsonify({"success": True, "title": info.get("title"), "download_url": url})
    except Exception as e:
        return jsonify({"error": str(e)}), 502

@app.route("/insta")
def insta():
    link = request.args.get("link", "").strip()
    if not link or not is_ig(link):
        return jsonify({"error": "invalid link"}), 400
    try:
        info = extract(link, get_opts())
        entries = info.get("entries") or [info]
        media = []
        for e in entries:
            for f in e.get("formats") or []:
                if f.get("vcodec") not in (None, "none") and f.get("url"):
                    media.append({"type": "video", "url": f["url"]})
                    break
            else:
                if e.get("url"):
                    media.append({"type": "image", "url": e["url"]})
        return jsonify({"success": True, "count": len(media), "media": media})
    except Exception as e:
        return jsonify({"error": str(e)}), 502

@app.route("/auto")
def auto():
    link = request.args.get("link", "").strip()
    if not link:
        return jsonify({"error": "missing link"}), 400
    if is_yt(link): return yt()
    if is_fb(link): return fb()
    if is_ig(link): return insta()
    return jsonify({"error": "unsupported"}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
