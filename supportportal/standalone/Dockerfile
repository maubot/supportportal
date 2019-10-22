FROM dock.mau.dev/maubot/maubot:standalone

ENV UID=1337 \
    GID=1337

COPY . /opt/maubot/supportportal
WORKDIR /opt/maubot/supportportal

VOLUME /data

CMD ["/opt/maubot/supportportal/supportportal/standalone/docker-run.sh"]
