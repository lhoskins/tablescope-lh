#!/usr/bin/env bash
# Bootstrap a Let's Encrypt certificate for the nginx reverse proxy.
#
# nginx will not start its 443 server block without a certificate, and certbot
# needs nginx (port 80 webroot) to answer the ACME HTTP-01 challenge. This
# script breaks that cycle: it installs a throwaway self-signed cert, starts
# nginx, then replaces it with a real Let's Encrypt cert and reloads.
#
# Run it once on the host (from the compose project directory):
#   ./nginx/init-letsencrypt.sh
set -euo pipefail

domain="app.tablescope.cloud"
email="${LETSENCRYPT_EMAIL:-leonard.hoskins@gmail.com}"
# Set STAGING=1 to use Let's Encrypt's staging CA while testing (avoids rate limits).
staging="${STAGING:-0}"
rsa_key_size=4096

compose() { docker compose "$@"; }

cert_path="/etc/letsencrypt/live/$domain"

echo "### Creating a temporary self-signed certificate for $domain ..."
compose run --rm --entrypoint "\
  sh -c 'mkdir -p $cert_path && \
  openssl req -x509 -nodes -newkey rsa:$rsa_key_size -days 1 \
    -keyout $cert_path/privkey.pem \
    -out $cert_path/fullchain.pem \
    -subj /CN=$domain'" certbot

echo "### Starting nginx ..."
compose up -d nginx
sleep 5

echo "### Deleting the temporary certificate ..."
compose run --rm --entrypoint "\
  rm -rf /etc/letsencrypt/live/$domain \
         /etc/letsencrypt/archive/$domain \
         /etc/letsencrypt/renewal/$domain.conf" certbot

echo "### Requesting a Let's Encrypt certificate for $domain ..."
staging_arg=""
if [ "$staging" != "0" ]; then staging_arg="--staging"; fi

compose run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    $staging_arg \
    --email $email \
    -d $domain \
    --rsa-key-size $rsa_key_size \
    --agree-tos \
    --no-eff-email \
    --force-renewal" certbot

echo "### Reloading nginx ..."
compose exec nginx nginx -s reload

echo "### Done. https://$domain should now serve a valid certificate."
