# Hosting and deployment

The site uses the same Apache server as Story Engine and ActionFlow 2, with a separate virtual host, document root and
certificate.

| Setting | Value |
| --- | --- |
| Hostname | modularsprites.bionic-productions.com |
| A record | 178.254.18.206 |
| DNS provider | 1blu |
| SSH host | v45082.1blu.de |
| Site root | /var/www/modularsprites.bionic-productions.com |
| Active document root | /var/www/modularsprites.bionic-productions.com/current |
| Releases | /var/www/modularsprites.bionic-productions.com/releases/ |
| Certificate | Dedicated Certbot certificate for modularsprites.bionic-productions.com |

## First deployment

1. Add the A record and check it resolves. Do not add an AAAA record unless the server has working IPv6 for this host.
2. Back up the Apache site configuration under `/var/backups` before adding the new host. Keep the existing sites and
   certificates intact.
3. Create the site root, `releases` and `acme/.well-known/acme-challenge` with readable permissions.
4. Commit and push `main`. Run `website/scripts/deploy.sh --stage-only` to upload and verify the first release without
   activating it.
5. Point `current` at that release. Install `apache-http.conf` as
   `/etc/apache2/sites-available/modularsprites.bionic-productions.com.conf` without the rewrite lines until HTTPS is
   ready. Enable the site, run `apache2ctl configtest` and reload Apache.
6. Check that the hostname serves the site, then obtain the certificate with the existing Certbot account:
   `certbot certonly --webroot -w /var/www/modularsprites.bionic-productions.com/acme --cert-name modularsprites.bionic-productions.com -d modularsprites.bionic-productions.com --non-interactive`.
7. Install `apache-https.conf` as `modularsprites.bionic-productions.com-ssl.conf` and the complete HTTP configuration
   with its HTTPS redirect. Enable the SSL site, run `apache2ctl configtest`, reload Apache.
8. Verify HTTPS with normal certificate validation, the HTTP redirect, several pages, images and search, and the other
   sites on the server.
9. `reload-apache.sh` is the Certbot deploy hook that makes Apache load renewed certificates. The server already has it
   as `/etc/letsencrypt/renewal-hooks/deploy/20-reload-apache` (installed for Story Engine; it covers every
   certificate). Dry-run the renewal of this certificate with `--run-deploy-hooks`.

The ACME challenge path stays available over HTTP for renewals. No credentials or private keys belong in this
repository.

## Later deployments

Run `website/scripts/deploy.sh` from a clean, pushed `main`. It builds strictly, runs the site checker, uploads a new
versioned release, verifies every file, switches the `current` symlink and checks the public `build-info.json` and a few
pages. If that final check fails it restores the previous release.

`--dry-run` builds and checks the server without uploading. `--stage-only` uploads and verifies without changing
`current`.

## Rollback

List `/var/www/modularsprites.bionic-productions.com/releases` and choose a previous release. Create a temporary
symlink to it next to `current`, then replace `current` with `mv -Tf`. Check the homepage and `build-info.json` again.
Changing the symlink needs no Apache reload; configuration changes need `apache2ctl configtest` and a reload.
