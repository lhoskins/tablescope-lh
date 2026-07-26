FROM alpine:3.20

RUN apk add --no-cache logrotate

COPY tablescope-teiid /etc/logrotate.d/tablescope-teiid
RUN chmod 644 /etc/logrotate.d/tablescope-teiid

CMD ["sh", "-c", "while true; do /usr/sbin/logrotate -s /tmp/logrotate.status /etc/logrotate.d/tablescope-teiid; sleep 3600; done"]
