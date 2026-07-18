# bose_st300

A small, self-hosted web remote for the **Bose SoundTouch 300** soundbar — a drop-in
replacement for the discontinued Bose SoundTouch app.

## Why this exists

Bose has **ended support for the SoundTouch generation of products**. On **6 May 2026**
the SoundTouch cloud was shut down, and the official SoundTouch mobile app no longer
works — no updates, and the account-backed features are gone.

The speaker hardware is fine, though. Every SoundTouch device still exposes a **local
control interface on your LAN** that the shutdown didn't touch:

- an HTTP control API on **port 8090**, and
- a WebSocket push feed ("gabbo") on **port 8080** for real-time state.

This project talks to those directly — **no cloud, no account, no internet required** —
so the speaker keeps working long after Bose walked away from it.

> **Which speaker?** Built for and tested against the **Bose SoundTouch 300** (firmware
> 27.x). Other SoundTouch models share the same local API and will mostly work, but the
> product-specific bits (bass/treble, per-speaker levels, surround/bass-module toggles,
> HDMI/TV source, speech mode) are validated only on the SoundTouch 300.

## What it controls

- **Volume**, mute, power (standby)
- **Transport** — play/pause, next/previous (for streaming sources)
- **Bass & treble** — bipolar −100…+100, like the remote's bass adjust
- **Speaker levels** — centre and surround trim, bipolar around a neutral 0
- **Speakers** — enable/disable the surround speakers and bass module
- **Speech mode** — Normal / Dialog for TV audio
- **Source** — TV, HDMI, Bluetooth
- **Live now-playing** with album art, updated in real time
- **Rename** the speaker from the app
- **Light / dark** theme (Catppuccin)

Spotify and Apple Music are **shown and controlled**, but started from your phone — they
arrive over Spotify Connect / AirPlay, which never depended on the Bose cloud. **Presets
are not supported**: their content could only be resolved by Bose's servers, so they no
longer load.

## Quick start (Docker)

```bash
cp .env.example .env          # set BOSE_HOST to your speaker's IP/hostname
docker compose up -d --build  # serves the app at http://<host>/bose
```

The container must run on a host that can reach the speaker on ports 8090 and 8080. See
[`deploy/README-deploy.md`](deploy/README-deploy.md) for reverse-proxy and networking
notes (subpath hosting, VLAN routing, running behind an existing web server).

## Local development

```bash
uv sync
uv run python -m views.web.app                 # http://localhost:5001
uv run python -m unittest discover tests/ -v   # tests (unittest, not pytest)
```

Set the speaker address with the `BOSE_HOST` env var or `config.toml`; if unset, the app
discovers the speaker over mDNS.

## How it works

- `soundtouch/` — device layer: HTTP client, XML↔dataclass models, the gabbo WebSocket
  bridge, and mDNS discovery.
- `views/web/` — a Flask app that proxies the speaker's XML as JSON, streams live updates
  over Server-Sent Events, and serves a mobile-first single-page UI. It's subpath-aware
  (via `X-Forwarded-Prefix`) so it can live under `/bose` behind a reverse proxy.
- `tests/` — parser tests against anonymised XML captured from a real device.

**Single worker on purpose:** the gabbo bridge lives in-process and holds the SSE
subscribers, so the app runs one gunicorn worker with threads, never multiple workers.

## License

MIT — see [LICENSE](LICENSE).
