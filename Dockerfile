FROM python:3.12-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl unzip git ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Deno install (JavaScript runtime for YouTube challenges)
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh
ENV PATH="/usr/local/bin:${PATH}"

# Verify Deno
RUN deno --version

# Python packages - yt-dlp[default] ZAROORI hai EJS ke liye
RUN pip install --no-cache-dir "yt-dlp[default]" flask bgutil-ytdlp-pot-provider

# Background mein bgutil POT provider start karo
# Yeh YouTube HD formats unlock karega
RUN git clone --single-branch --branch 2.0.2 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil \
    && cd /opt/bgutil/server \
    && deno install --allow-scripts=npm:canvas --frozen

# Startup script: POT provider background mein, phir Flask
COPY start.sh /start.sh
RUN chmod +x /start.sh

COPY app.py /app.py
WORKDIR /

EXPOSE 10000

CMD ["/start.sh"]
