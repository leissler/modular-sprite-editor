#!/bin/sh
# Certbot deploy hook: load renewed certificates after a successful renewal.
set -eu
/usr/sbin/apache2ctl configtest
/usr/bin/systemctl reload apache2
