#!/bin/sh
# Run by the nginx image's entrypoint before it fills in the templates
# (20-envsubst-on-templates.sh): picks the server block NGINX_MODE asks
# for, and refuses to start HTTPS without a certificate to serve.
set -eu

mode="${NGINX_MODE:-https}"
source="/etc/nginx/django-generic/${mode}.conf.template"

if [ ! -f "$source" ]; then
    echo "NGINX_MODE must be https or http, not '${mode}'." >&2
    exit 1
fi

if [ "$mode" = "https" ]; then
    for file in "${NGINX_CERT:-}" "${NGINX_CERT_KEY:-}"; do
        if [ -z "$file" ] || [ ! -r "$file" ]; then
            echo "NGINX_MODE=https: no certificate at '${file}'. Mount the" \
                 "folder holding it with NGINX_CERTS_DIR and name the" \
                 "files with NGINX_CERT and NGINX_CERT_KEY, or use" \
                 "NGINX_MODE=http." >&2
            exit 1
        fi
    done
fi

mkdir -p /etc/nginx/templates
cp "$source" /etc/nginx/templates/default.conf.template
