import os, re, logging, random, concurrent.futures, requests
from flask import Flask, request, jsonify
import yt_dlp

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ---------- PROXY (simple) ----------
SOURCES = [
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000",
    "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
]

def get_proxy():
    proxies = set()
    def fetch(u):
        try:
            r = requests.get(u, timeout=3, headers={"User-Agent": "Mozilla/5.0"})
            return re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}:\d+\b', r.text)
        except: return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        for res in ex.map(fetch, SOURCES):
            proxies.update(res)
    proxies = list(proxies)
    random.shuffle(proxies)
    # test first 10 in parallel
    def test(p):
        try:
            requests.get("http://httpbin.org/ip",
                         proxies={"http": f"http://{p}", "https": f"http://{p}"},
                         timeout=2)
            return p
        except: return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        for r in ex.map(test, proxies[:10]):
            if r: return r
    return None

# ---------- URL CHECK ----------
def is_yt(u): return bool(re.match(r"^(https?://)?(www\.|m\.)?(youtube\.com|youtu\.be)/", u, re.I))
def is_fb(u): return bool(re.match(r"^(https?://)?(www\.|m\.|web\.)?(facebook\.com|fb\.watch|fb\.me)/", u, re.I))
def is_ig(u): return bool(re.match(r"^(https?://)?(www\.)?instagram\.com/", u, re.I))

# ---------- YT-DLP ----------
QUALITY = {
    "144p": ("worst[height<=144]", 144),
    "360p": ("best[height<=360]", 360),
    "480p": ("best[height<=480]", 480),
    "720p": ("best[height<=720]", 720),
    "1080p": ("best[height<=1080]", 1080),
    "best": ("best", 9999),
    "audio": ("bestaudio/best", 0),
}

BASE = {
    "quiet": True, "no_warnings": True, "noplaylist": True,
    "skip_download": True, "socket_timeout": 10, "retries": 1,
    "nocheckcertificate": True,
    "http_headers": {"User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/151.0.0.0 Mobile Safari/537.36"},
}

def extract(url, opts):
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=False)
        if info.get("_type") == "playlist":
            info = (info.get("entries") or [None])[0]
        return info

def run(link, quality="720p"):
    fmt, _ = QUALITY.get(quality, QUALITY["720p"])
    opts = dict(BASE); opts["format"] = fmt
    p = get_proxy()
    if p: opts["proxy"] = f"http://{p}"
    try:
        info = extract(link, opts)
    except Exception:
        if p:  # retry without proxy
            opts.pop("proxy", None); info = extract(link, opts)
        else: raise
    url = info.get("url")
    if not url and info.get("formats"):
        url = info["formats"][-1]["url"]
    return {"success": True, "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration_string"),
            "download_url": url, "proxy": p or "direct"}

# ---------- ROUTES ----------
@app.route("/")
def home(): return jsonify({"endpoints": ["/yt?link=&quality=", "/fb?link=", "/insta?link=", "/auto?link="]})

@app.route("/yt")
def yt():
    link = request.args.get("link","").strip()
    q = request.args.get("quality","720p").lower()
    if not link or not is_yt(link): return jsonify({"error":"invalid link"}),400
    try: return jsonify(run(link,q))
    except Exception as e: return jsonify({"error":str(e)}),502

@app.route("/fb")
def fb():
    link = request.args.get("link","").strip()
    if not link or not is_fb(link): return jsonify({"error":"invalid link"}),400
    try:
        info = extract(link, {**BASE, "format":"best"})
        url = info.get("url") or info["formats"][-1]["url"]
        return jsonify({"success":True,"title":info.get("title"),"download_url":url})
    except Exception as e: return jsonify({"error":str(e)}),502

@app.route("/insta")
def insta():
    link = request.args.get("link","").strip()
    if not link or not is_ig(link): return jsonify({"error":"invalid link"}),400
    try:
        info = extract(link, BASE)
        entries = info.get("entries") or [info]
        media = []
        for e in entries:
            for f in e.get("formats") or []:
                if f.get("vcodec") not in (None,"none") and f.get("url"):
                    media.append({"type":"video","url":f["url"]}); break
            else:
                if e.get("url"): media.append({"type":"image","url":e["url"]})
        return jsonify({"success":True,"count":len(media),"media":media})
    except Exception as e: return jsonify({"error":str(e)}),502

@app.route("/auto")
def auto():
    link = request.args.get("link","").strip()
    if not link: return jsonify({"error":"missing link"}),400
    if is_yt(link): return yt()
    if is_fb(link): return fb()
    if is_ig(link): return insta()
    return jsonify({"error":"unsupported"}),400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))
