import os
import tempfile
import yt_dlp
from flask import Flask, request, jsonify, send_file

app = Flask(__name__)

DOWNLOAD_DIR = tempfile.gettempdir()

# Render pe cookies Secret File se aayengi
COOKIES_PATH = "/etc/secrets/cookies.txt"

def get_ydl_opts(quality="best", fmt="mp4"):
    if fmt == "mp3":
        ydl_format = "bestaudio/best"
        postprocessors = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
        ext = "mp3"
    else:
        if quality == "best":
            ydl_format = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        else:
            ydl_format = (
                f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/"
                f"best[height<={quality}][ext=mp4]/best"
            )
        postprocessors = [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}]
        ext = "mp4"

    opts = {
        "format": ydl_format,
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "postprocessors": postprocessors,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "restrictfilenames": True,
    }

    # Cookies agar available hain to use karo (Render pe zaroori)
    if os.path.exists(COOKIES_PATH):
        opts["cookiefile"] = COOKIES_PATH

    return opts, ext


@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "endpoints": "/yt-video-download?link=<url>&quality=360|720|best&format=mp4|mp3"
    })


@app.route("/yt-video-download")
def yt_download():
    link = request.args.get("link")
    quality = request.args.get("quality", "best")
    fmt = request.args.get("format", "mp4").lower()

    if not link:
        return jsonify({"error": "missing link"}), 400

    try:
        ydl_opts, ext = get_ydl_opts(quality, fmt)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            filename = ydl.prepare_filename(info)

            base, _ = os.path.splitext(filename)
            for candidate_ext in (ext, "mp4", "mp3", "m4a", "webm"):
                candidate = f"{base}.{candidate_ext}"
                if os.path.exists(candidate):
                    filename = candidate
                    break

            if not os.path.exists(filename):
                return jsonify({"error": "download failed"}), 500

            title = info.get("title", "video")
            safe_title = "".join(c for c in title if c.isalnum() or c in " -_")[:100]

            return send_file(
                filename,
                as_attachment=True,
                download_name=f"{safe_title}.{ext}",
                mimetype="audio/mpeg" if ext == "mp3" else "video/mp4",
            )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
