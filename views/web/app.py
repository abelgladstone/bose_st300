"""Flask front end: proxies the speaker's XML API as JSON and streams live updates."""

from __future__ import annotations

import json
import logging
import queue

from flask import Flask, Response, jsonify, render_template, request, url_for

from soundtouch.api import SoundTouchClient, SoundTouchError
from soundtouch.discovery import Config, resolve_host
from soundtouch.notify import NotificationBridge
from soundtouch.version import RELEASE_NOTES, __version__

_LOGGER = logging.getLogger(__name__)


class PrefixMiddleware:
    """Honour X-Forwarded-Prefix so the app can be mounted under a subpath (e.g. /bose).

    The reverse proxy strips the prefix before forwarding, so PATH_INFO is already
    correct; setting SCRIPT_NAME makes url_for() and request.script_root emit the prefix,
    which is what the templates and the injected JS base path rely on.
    """

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        prefix = environ.get("HTTP_X_FORWARDED_PREFIX", "").rstrip("/")
        if prefix:
            environ["SCRIPT_NAME"] = prefix
        return self.wsgi_app(environ, start_response)


def create_app(host: str | None = None) -> Flask:
    config = Config.load()
    device_host = host or resolve_host(config)

    app = Flask(__name__)
    # Serve edited templates/static without a restart during local iteration.
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True
    app.wsgi_app = PrefixMiddleware(app.wsgi_app)
    client = SoundTouchClient(device_host)
    bridge = NotificationBridge(device_host)
    bridge.start()

    app.config["CLIENT"] = client
    app.config["BRIDGE"] = bridge

    @app.errorhandler(SoundTouchError)
    def _handle_device_error(err: SoundTouchError):
        _LOGGER.warning("device error: %s", err)
        return jsonify(error=str(err)), 502

    @app.get("/")
    def index():
        return render_template(
            "index.html", device_name=config.name or device_host, version=__version__
        )

    @app.get("/api/about")
    def about():
        return jsonify(version=__version__, release_notes=RELEASE_NOTES)

    @app.get("/healthz")
    def healthz():
        # Liveness only -- deliberately does not touch the speaker, so a sleeping or
        # briefly unreachable speaker never marks the container unhealthy.
        return jsonify(status="ok")

    @app.get("/manifest.webmanifest")
    def manifest():
        # Served dynamically so start_url and the icon carry the mount prefix; a static
        # manifest with absolute "/" paths would break under /bose.
        return jsonify(
            {
                "name": f"SoundTouch — {config.name}" if config.name else "SoundTouch",
                "short_name": "SoundTouch",
                "start_url": url_for("index"),
                "scope": url_for("index"),
                "display": "standalone",
                "background_color": "#0b0b0d",
                "theme_color": "#0b0b0d",
                "orientation": "portrait",
                "icons": [
                    {
                        "src": url_for("static", filename="icon.svg"),
                        "sizes": "any",
                        "type": "image/svg+xml",
                        "purpose": "any maskable",
                    }
                ],
            }
        )

    @app.get("/api/state")
    def state():
        return jsonify(client.state().to_dict())

    @app.post("/api/volume")
    def set_volume():
        client.set_volume(int(request.json["value"]))
        return jsonify(ok=True)

    @app.post("/api/key")
    def press_key():
        client.press_key(request.json["value"])
        return jsonify(ok=True)

    @app.post("/api/source")
    def select_source():
        payload = request.json
        client.select_source(payload["source"], payload.get("sourceAccount", ""))
        return jsonify(ok=True)

    @app.post("/api/tone")
    def set_tone():
        payload = request.json
        tone = client.set_tone(bass=payload.get("bass"), treble=payload.get("treble"))
        return jsonify(bass=tone.bass.value, treble=tone.treble.value)

    @app.post("/api/levels")
    def set_levels():
        payload = request.json
        levels = client.set_levels(center=payload.get("center"), surround=payload.get("surround"))
        return jsonify(center=levels.center.value, surround=levels.surround.value)

    @app.post("/api/dsp")
    def set_dsp():
        dsp = client.set_audio_mode(request.json["audiomode"])
        return jsonify(audio_mode=dsp.audio_mode)

    @app.post("/api/name")
    def set_name():
        info = client.set_name(request.json["name"])
        return jsonify(name=info.name)

    @app.post("/api/speaker")
    def set_speaker():
        payload = request.json
        speakers = client.set_speaker_active(payload["name"], bool(payload["active"]))
        return jsonify(items=[{"name": s.name, "active": s.active} for s in speakers.items])

    @app.get("/api/events")
    def events():
        def stream():
            q = bridge.subscribe()
            try:
                yield ": connected\n\n"
                while True:
                    try:
                        message = q.get(timeout=20)
                    except queue.Empty:
                        yield ": keepalive\n\n"  # keeps proxies from dropping the stream
                        continue
                    yield f"event: {message['event']}\ndata: {json.dumps(message['data'])}\n\n"
            finally:
                bridge.unsubscribe(q)

        return Response(
            stream(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = Config.load()
    app = create_app()
    # threaded=True is required: each SSE client holds a worker for its whole session.
    app.run(host=config.server_host, port=config.server_port, threaded=True)


if __name__ == "__main__":
    main()
