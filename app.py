import os
import re
from flask import Flask, request, jsonify
import yt_dlp

app = Flask(__name__)

# Har platform ke liye alag player_client try karo
YT_CLIENTS = ["tv", "mweb", "web_safari", "android_vr"]

def is_youtube(u):
    return bool(re.match(r"^(https?://)?(www\.|m\.)?(youtube\.com|youtu\.be)/", u, re.I))

def is_ytmusic(u):
    return bool(re.match(r"^(https?://)?music\.youtube\.com/", u, re.I))

def is_facebook(u):
    return bool(re.match(r"^(https?://)?(www\.|m\.|web\.)?(facebook\.com|fb\.watch|fb\.me)/", u, re.I))

def is_instagram(u):
    return bool(re.match(r"^(https?://)?(www\.)?instagram\.com/", u, re.I))

def try_extract(url, quality="best", max_h=99999):
    """Multiple player_clients try karo, pehla successful return karo."""
    for client in YT_CLIENTS:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
            "socket_timeout": 20,
            "extractor_args": {
                "youtube": {"player_client": [client]},
            },
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
        }
        if quality == "audio":
            opts["format"] = "bestaudio/best"
        else:
            opts["format"] = f"bestvideo[height<={max_h}]+bestaudio/best[height<={max_h}]/best"

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and (info.get("url") or info.get("formats")):
                    return info
        except Exception:
            continue
    raise Exception("All clients failed. YouTube is blocking this server IP. Cookies or proxy required.")

def extract_best(info, want_audio=False, max_h=99999):
    formats = info.get("formats") or []
    if want_audio:
        auds = [f for f in formats if f.get("vcodec") == "none" and f.get("url")]
        if auds:
            return max(auds, key=lambda f: f.get("abr") or 0)
        return None
    vids = [f for f in formats if f.get("vcodec") not in (None, "none") and f.get("url")]
    if not vids:
        return None
    within = [f for f in vids if (f.get("height") or 0) <= max_h]
    return max(within or vids, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))

@app.route("/")
def home():
    return jsonify({"endpoints": {
        "/yt": "?link=YT_URL&quality=720p|1080p|audio",
        "/ytmusic": "?link=music.youtube.com/...",
        "/fb": "?link=FB_URL",
        "/insta": "?link=INSTA_URL",
        "/auto": "?link=ANY&quality=720p",
    }})

@app.route("/yt")
def yt():
    link = request.args.get("link", "").strip()
    quality = request.args.get("quality", "720p").lower()
    if not link or not is_youtube(link):
        return jsonify({"error": "bad link"}), 400

    is_audio = quality == "audio"
    max_h = int(quality.replace("p", "")) if quality.endswith("p") else 99999

    try:
        info = try_extract(link, quality, max_h)
        best = extract_best(info, want_audio=is_audio, max_h=max_h)
        url = (best or {}).get("url") or info.get("url")
        if not url:
            return jsonify({"error": "no format"}), 404
        return jsonify({
            "success": True,
            "title": info.get("title"),
            "duration": info.get("duration_string"),
            "quality": f"{best.get('height')}p" if best and best.get("height") else quality,
            "ext": best.get("ext") if best else info.get("ext"),
            "download_url": url,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502

@app.route("/ytmusic")
def ytmusic():
    link = request.args.get("link", "").strip()
    quality = request.args.get("quality", "audio").lower()
    if not link or not is_ytmusic(link):
        return jsonify({"error": "bad link"}), 400

    is_audio = quality == "audio"
    max_h = int(quality.replace("p", "")) if quality.endswith("p") else 99999

    try:
        info = try_extract(link, quality, max_h)
        best = extract_best(info, want_audio=is_audio, max_h=max_h)
        url = (best or {}).get("url") or info.get("url")
        return jsonify({
            "success": True,
            "title": info.get("track") or info.get("title"),
            "artist": info.get("artist") or info.get("uploader"),
            "download_url": url,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502

@app.route("/fb")
def fb():
    link = request.args.get("link", "").strip()
    if not link or not is_facebook(link):
        return jsonify({"error": "bad link"}), 400
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "format": "best"}) as ydl:
            info = ydl.extract_info(link, download=False)
        best = extract_best(info)
        return jsonify({
            "success": True,
            "title": info.get("title") or info.get("description"),
            "quality": f"{best.get('height')}p" if best and best.get("height") else "source",
            "download_url": (best or {}).get("url") or info.get("url"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502

@app.route("/insta")
def insta():
    link = request.args.get("link", "").strip()
    if not link or not is_instagram(link):
        return jsonify({"error": "bad link"}), 400
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(link, download=False)
        entries = info.get("entries") or [info]
        media = []
        for e in entries:
            fmts = e.get("formats") or []
            vids = [f for f in fmts if f.get("vcodec") not in (None, "none") and f.get("url")]
            if vids:
                best = max(vids, key=lambda f: f.get("height") or 0)
                media.append({"type": "video", "url": best["url"], "ext": best.get("ext", "mp4")})
            elif e.get("url"):
                media.append({"type": "image", "url": e["url"], "ext": "jpg"})
        return jsonify({"success": True, "count": len(media), "media": media})
    except Exception as e:
        return jsonify({"error": str(e)}), 502

@app.route("/auto")
def auto():
    link = request.args.get("link", "").strip()
    if is_ytmusic(link): return ytmusic()
    if is_youtube(link): return yt()
    if is_facebook(link): return fb()
    if is_instagram(link): return insta()
    return jsonify({"error": "unsupported"}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
