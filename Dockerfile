FROM mockserver/mockserver:latest

COPY expectations/ /config/

ENV MOCKSERVER_INITIALIZATION_JSON_PATH=/config/*.json \
    SERVER_PORT=1080

EXPOSE 1080
