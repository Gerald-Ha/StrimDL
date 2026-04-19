FROM alpine:3.19.2


RUN apk add --no-cache tzdata python3 ffmpeg \
    && mkdir -p /app \
    && apk add --virtual build-deps curl \
    && curl -sL -o /usr/bin/yt-dlp 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp' \
    && chmod +x /usr/bin/yt-dlp \
    && apk del build-deps


COPY server.py index.html login.html /app/
COPY css /app/css
COPY image /app/image




RUN chmod +x /app/server.py


WORKDIR /app


EXPOSE 10001


ENV PYTHONUNBUFFERED=1


CMD [ "/app/server.py" ]
