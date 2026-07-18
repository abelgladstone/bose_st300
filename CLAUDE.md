# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A local web remote for the **Bose SoundTouch 300**, replacing the Bose app that stopped
working when Bose shut the SoundTouch cloud on 2026-05-06. The speaker's local control
interface is untouched by the shutdown: an HTTP API on **:8090** and a WebSocket push feed
("gabbo") on **:8080**. This app drives both directly — no cloud, no account.

## Commands

```bash
uv sync                                          # install deps
uv run python -m views.web.app                   # dev server -> http://localhost:5001
uv run python -m unittest discover tests/ -v     # tests (unittest, NOT pytest)
```

The speaker address comes from `config.toml` (`device.host`), overridden by the env var
`BOSE_HOST`. `BOSE_NAME` sets the display name.

## Architecture

- **`soundtouch/`** — device layer, no Flask:
  - `api.py` — `SoundTouchClient`: HTTP GET/POST, XML↔dataclass, all reads/writes. `State`
    is the one aggregate snapshot the UI needs.
  - `models.py` — dataclasses parsing/serialising the device XML.
  - `notify.py` — `NotificationBridge`: connects the gabbo WebSocket, parses push frames,
    fans them out to subscribers (an in-process event bus).
  - `discovery.py` — `Config` (from `config.toml` + env) and mDNS discovery fallback.
- **`views/web/`** — Flask front end:
  - `app.py` — JSON REST proxy over the client, a Server-Sent-Events endpoint fed by the
    bridge, plus a dynamic manifest. `PrefixMiddleware` makes it mountable under a subpath.
  - `templates/index.html`, `static/{app.js,style.css}` — mobile-first single page.
- **`tests/`** — parser tests against XML **captured from a real device** (`tests/fixtures/`).
- `wsgi.py` — gunicorn entrypoint. `Dockerfile` / `docker-compose.yml` / `deploy/` — container + proxy.

### Two load-bearing constraints — do not break these

1. **Single gunicorn worker.** The gabbo bridge lives in-process and holds the SSE
   subscribers. A second worker would open a second bridge and split subscribers, so events
   would miss clients. Concurrency is threads (`gthread`), never workers. See `wsgi.py`.
2. **Subpath-tolerant.** The app is served behind a reverse proxy under `/bose`. All asset
   and API URLs derive from `window.BOSE_BASE` (JS) / `request.script_root` (Flask), driven
   by the `X-Forwarded-Prefix` header via `PrefixMiddleware`. Never hardcode leading-slash
   absolute paths — test at both `/` and under a subpath.

## Device API notes (learned empirically — verify on-device before trusting docs)

- **Bass is not `/bass`.** `/bassCapabilities` reports `bassAvailable=false` on the ST300.
  Bass/treble live on `/audioproducttonecontrols` (range −100…+100, step 25).
- **Bipolar controls.** Bass, treble, and speaker levels (`/audioproductlevelcontrols`,
  center + surround) are signed, centred on 0 — the UI renders them fill-from-centre.
- **Write bodies echo only `value`** (tone/level) — sending `minValue`/`maxValue`/`step` is rejected.
- **Speaker enable/disable** (`/audiospeakerattributeandsetting`, `rear` + `subwoofer01`):
  accepts **only** a bare `active` attribute (`<rear active="false"/>`). Including
  `available`/`wireless`/`controllable` returns `Invalid Input`.
- **`/key` needs press *and* release** or the device ignores it.
- **Presets are dead.** Their content only Bose's cloud could resolve; any recall now lands
  on `source="INVALID_SOURCE"`. Removed from the UI — do not re-add.
- **Non-TV sources report `AUDIO_MODE_DIRECT`**, which the device neither lists in
  `supportedaudiomodes` nor accepts as a write; the speech-mode toggle shows as N/A then.
- **Spotify/Apple** arrive via Spotify Connect / AirPlay (bypass the dead cloud) — shown and
  controllable, but started from the phone, not here.

## Deployment

Built as a container; served under `/bose` behind a reverse proxy so the port is hidden.
Runs on any host that can reach the speaker's IP on :8090 and :8080. Config comes from the
`BOSE_HOST` / `BOSE_NAME` env vars (see `.env.example`). See `README.md` and
`deploy/README-deploy.md` for reverse-proxy and networking notes.
