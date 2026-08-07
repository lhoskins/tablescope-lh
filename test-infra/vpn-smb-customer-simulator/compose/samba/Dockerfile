FROM alpine:3.19

RUN apk add --no-cache samba

COPY smb.conf /etc/samba/smb.conf
COPY add-user.sh /usr/local/bin/add-user.sh
RUN chmod +x /usr/local/bin/add-user.sh

# Create the read-only service account and group without a valid shell.
RUN addgroup -S tablescope && \
    adduser -S -G tablescope -H -s /sbin/nologin tablescope_ro

EXPOSE 445

CMD ["/usr/local/bin/add-user.sh"]
