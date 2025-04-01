FROM alpine:3.19.2

# System-Abhängigkeiten installieren: Zeitzone, Python, ffmpeg
RUN apk add --no-cache tzdata python3 ffmpeg \
    && mkdir -p /app \
    && apk add --virtual build-deps curl \
    && curl -sL -o /usr/bin/yt-dlp 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp' \
    && chmod +x /usr/bin/yt-dlp \
    && apk del build-deps

# Server-Skripte und HTML-Dateien kopieren
COPY server.py index.html /app/


# Server ausführbar machen
RUN chmod +x /app/server.py

# Arbeitsverzeichnis setzen
WORKDIR /app

# Port freigeben
EXPOSE 10001

# Ausgabe direkt anzeigen (z. B. für Docker Logs)
ENV PYTHONUNBUFFERED=1

# Startbefehl
CMD [ "/app/server.py" ]
