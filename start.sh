#!/bin/bash

# POT provider background mein start karo
cd /opt/bgutil/server
node build/main.js --port 4416 &
# ya agar Deno use karna ho:
# deno run --allow-env --allow-net --allow-ffi=. --allow-read=. ../src/main.ts --port 4416 &

# Thoda wait karo provider start hone ka
sleep 5

# Flask app start karo
cd /
python app.py
