# FabOS on Debian/Ubuntu Server

This is the preferred no-license-cost server path for a spare 64-bit PC. It keeps FabOS persistent data outside the Git checkout and runs the API as a systemd service bound to localhost. Caddy should terminate HTTPS and proxy `/api/*` to `127.0.0.1:8000`.

## Requirements

- 64-bit Debian 12/Ubuntu Server LTS
- Python 3.11+ and venv support
- Git
- A persistent disk with regular backups
- Caddy on the same host, or another trusted reverse proxy

Do not expose port 8000 directly to the Internet.

## First run

Clone the repository somewhere such as `/opt/fabos`, create a virtual environment, install the package, and create `/var/lib/fabos` for production data. Keep secrets in `/etc/fabos/server.env` with permissions restricted to the FabOS service account.

The service template in this directory runs `python -m fabos_core.cli serve` with `FABOS_API_HOST=127.0.0.1`.

Run the setup commands in order:

`python -m fabos_core.cli init`
`python -m fabos_core.cli setup-owner`
`python -m fabos_core.cli setup-dns`
`python -m fabos_core.cli setup-stripe`
`python -m fabos_core.cli production-check`

`production-check` is read-only and fails closed when required production settings, HTTPS Stripe URLs, the webhook secret, persistent storage, or database integrity are missing. It also blocks production while the bootstrap `owner-password` remains active.

## Backups

Run `python -m fabos_core.cli backup` regularly and copy verified archives to storage independent of the server. A backup is not a recovery plan until a restore has been tested on a separate data directory.

## Firewall

Allow only SSH (if needed), HTTP 80, and HTTPS 443. Keep the FabOS API port bound to localhost. If SSH is enabled, use keys rather than password-only access and restrict administrative access appropriately.

## Updates

Pull updates into the application checkout, install dependencies into the same virtual environment, run the test suite, then restart the service. Never replace `/var/lib/fabos` during an application update.
