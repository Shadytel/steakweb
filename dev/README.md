# Local dev setup

Runs steakweb on your machine against a throwaway Postgres, no prod DB or SAML
IdP needed. Enough to click through the activation form and the directory.

There's no schema in the repo, so `dev/schema.sql` is reconstructed from the SQL
in `steakweb.py`. It's close enough that everything works, but if the real
schema turns up, drop it in and recreate the DB (`down -v` then `up`).

Everything dev-only is gated on `STEAKWEB_DEV`, so it's off in prod.

## Run it

1. Start Postgres (loads schema + seed on first boot, listens on `127.0.0.1:5433`):

       docker compose -f dev/docker-compose.yml up -d

2. Python deps:

       python3 -m venv .venv
       .venv/bin/pip install -r requirements.txt

   `python3-saml` may need system libs to build (Debian/Ubuntu:
   `sudo apt install pkg-config libxml2-dev libxmlsec1-dev libxmlsec1-openssl`).
   It's imported but unused in dev.

3. Config (`config.json` is gitignored):

       cp dev/config.dev.json config.json

4. Run:

       STEAKWEB_DEV=1 .venv/bin/python steakweb.py

   Serves on `http://127.0.0.1:8080`. If 8080's taken, set `STEAKWEB_DEV_PORT=8099`.

In prod (`STEAKWEB_DEV` unset) it serves over the unix socket like before. The
TCP port, `/dev/login`, and the non-secure cookie are dev-only.

## What to check

Swap `8080` for your port below.

Directory, no login:

- `/directory` — the 6 published rows, with the unpublished "Hidden Back Office"
  (4040) hidden and the `<script>` name (5050) shown as plain text, not run.
- `/api/directory.json` — same rows as JSON, just name + number.

Activation, needs a session:

- Hit `/dev/login` to fake a login (`?admin=1` to also be an admin). That drops
  you on the My Extensions page.
- In the Add a New Extension form:
  - letters (`ABCD`) → "Extension must be a four-digit number", no 500
  - out of range (`1999`, `7000`) → "Extension number must start with 2, 3, 4, 5, or 6"
  - a taken number (`2345`) → "That extension is already taken; please choose another"
  - a free number 2000–6999 → created, shows up in the list

## Done testing

    docker compose -f dev/docker-compose.yml down      # stop, keep data
    docker compose -f dev/docker-compose.yml down -v   # stop and wipe (re-seeds next up)
    rm -f config.json
