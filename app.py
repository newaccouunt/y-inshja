from flask import Flask, request, jsonify
import yt_dlp
import re
import time
import random

app = Flask(__name__)

def detect_platform(link: str) -> str:
    if re.search(r"instagram\.com", link): return "instagram"
    if re.search(r"(facebook\.com|fb\.watch|fb\.com)", link): return "facebook"
    if re.search(r"(youtube\.com|youtu\.be|youtube-nocookie\.com)", link): return "youtube"
    return "unknown"

def detect_ig_type(link: str) -> str:
    if "/stories/" in link: return "story"
    if "/reel" in link or "/reels/" in link: return "reel"
    if "/p/" in link: return "post"
    if "/tv/" in link: return "igtv"
    return "unknown"

def get_ydl_opts(platform: str, client_chain: list = None) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 30,
        "extractor_retries": 5,
        # Render Dockerfile mein Deno install hoga, isliye yeh path sahi hai
        "js_runtimes": {"deno": {}},
        "http_headers": {
            "User-Agent": random.choice([
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
            ])
        },
    }

    if platform == "youtube":
        # PO Token provider Render ke andar alag container mein chalega
        # Agar dono ek hi Dockerfile mein hain to localhost:4416 kaam karega
        clients = client_chain or ["mweb", "web"]
        opts["extractor_args"] = {
            "youtube": {
                "player_client": clients,
                "youtubepot-bgutilhttp:base_url": "http://127.0.0.1:4416",
            }
        }

    return opts

def extract_media(link: str, platform: str) -> dict:
    if platform == "youtube":
        client_chains = [["mweb"], ["web"], ["mweb", "web"], ["tv"]]
    else:
        client_chains = [None]

    last_error = None
    for chain in client_chains:
        for attempt in range(3):
            try:
                opts = get_ydl_opts(platform, chain)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(link, download=False)
                    if platform == "youtube":
                        heights = [f.get("height", 0) for f in info.get("formats", []) if f.get("height")]
                        max_h = max(heights) if heights else 0
                        if max_h <= 360:
                            last_error = Exception(f"Only {max_h}p, trying next client")
                            break
                    return info
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                if "page needs to be reloaded" in err_str:
                    time.sleep(5 + random.random() * 3)
                    continue
                break
    raise last_error

def normalize(info: dict, platform: str, media_type: str = None) -> dict:
    result = {
        "ok": True, "platform": platform, "type": media_type,
        "id": info.get("id"), "title": info.get("title") or info.get("description"),
        "thumbnail": info.get("thumbnail"), "duration": info.get("duration"),
        "author": info.get("uploader") or info.get("channel") or info.get("creator"),
        "author_url": info.get("uploader_url") or info.get("channel_url"),
        "medias": []
    }

    formats = info.get("formats") or []
    if not formats and info.get("url"):
        formats = [{"url": info["url"], "ext": info.get("ext", "mp4"), "vcodec": "unknown", "acodec": "unknown"}]

    seen = set()
    for f in formats:
        url = f.get("url")
        if not url or url in seen: continue
        seen.add(url)
        if url.endswith(".m3u8") or "manifest" in url: continue

        vcodec = f.get("vcodec", "none")
        acodec = f.get("acodec", "none")
        ftype = "video"
        if vcodec == "none" and acodec != "none": ftype = "audio"
        elif vcodec == "none" and acodec == "none": continue

        result["medias"].append({
            "url": url, "type": ftype, "ext": f.get("ext"),
            "quality": f.get("format_note") or f.get("resolution") or f.get("format_id"),
            "width": f.get("width"), "height": f.get("height"),
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "bitrate": f.get("abr") or f.get("tbr"),
        })

    result["medias"].sort(key=lambda x: (0 if x["type"] == "video" else 1, -(x.get("height") or 0)))
    return result

@app.route("/download", methods=["GET"])
def download():
    link = request.args.get("link") or request.args.get("url")
    if not link:
        return jsonify({"ok": False, "error": "Missing ?link="}), 400

    link = link.strip()
    platform = detect_platform(link)
    if platform == "unknown":
        return jsonify({"ok": False, "error": "Supported: IG, FB, YouTube"}), 400

    media_type = detect_ig_type(link) if platform == "instagram" else ("video" if platform in ("facebook", "youtube") else None)

    try:
        info = extract_media(link, platform)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Failed: {str(e)}", "platform": platform}), 500

    result = normalize(info, platform, media_type)
    result["source_link"] = link
    return jsonify(result)

@app.route("/", methods=["GET"])
def home():
    return jsonify({"api": "Render All-in-One Downloader", "usage": "/download?link=<URL>"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
