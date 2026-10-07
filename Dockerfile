# The Jump Room server room: node for the front door, Godot (headless) for the game servers it runs.
FROM node:24-bookworm-slim
ARG GODOT_VERSION=4.7.2
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl unzip libfontconfig1 libx11-6 libxcursor1 libxinerama1 libxi6 libxrandr2 libgl1 libasound2 libpulse0 && rm -rf /var/lib/apt/lists/*
WORKDIR /tmp/godot-download
RUN curl -fsSLO "https://github.com/godotengine/godot-builds/releases/download/${GODOT_VERSION}-stable/Godot_v${GODOT_VERSION}-stable_linux.x86_64.zip" \
 && curl -fsSLO "https://github.com/godotengine/godot-builds/releases/download/${GODOT_VERSION}-stable/SHA512-SUMS.txt" \
 && grep " Godot_v${GODOT_VERSION}-stable_linux.x86_64.zip$" SHA512-SUMS.txt | sha512sum -c - \
 && unzip "Godot_v${GODOT_VERSION}-stable_linux.x86_64.zip" \
 && mv "Godot_v${GODOT_VERSION}-stable_linux.x86_64" /usr/local/bin/godot \
 && chmod 755 /usr/local/bin/godot && rm -rf /tmp/godot-download
RUN useradd --create-home --uid 10001 room
WORKDIR /room
COPY index.mjs ./index.mjs
USER room
ENV PORT=10000 HUB_URL=https://jump-room.netlify.app DATA_DIR=/tmp/jump-room-server-room GODOT_BIN=/usr/local/bin/godot
EXPOSE 10000
CMD ["node", "index.mjs"]
