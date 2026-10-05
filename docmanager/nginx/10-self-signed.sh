#!/bin/sh
# Run by the nginx image's entrypoint before it starts nginx: a
# certificate signed by nobody but itself, made once and kept in the
# certs volume - so the browser's exception, once accepted, holds. A
# certificate mounted there instead (server.crt and server.key) is
# served as it is.
set -eu

dir=/etc/nginx/certs
mkdir -p "$dir"

if [ -s "$dir/server.crt" ] && [ -s "$dir/server.key" ]; then
    exit 0
fi

# SERVER_NAME, the machine's name on the network, beside localhost.
name="${SERVER_NAME:-localhost}"
names="DNS:localhost,IP:127.0.0.1"
if [ "$name" != "localhost" ]; then
    names="DNS:$name,$names"
fi

echo "No certificate in $dir: signing one for $names."
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
    -subj "/CN=$name" \
    -addext "subjectAltName=$names" \
    -keyout "$dir/server.key" -out "$dir/server.crt" 2>/dev/null
chmod 600 "$dir/server.key"
