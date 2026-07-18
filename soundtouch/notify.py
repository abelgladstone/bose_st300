"""Bridge the device's 'gabbo' WebSocket push feed (port 8080) onto an internal event bus.

The speaker pushes an XML <updates> document whenever anything changes -- including
changes made from the physical remote -- so the UI stays truthful without polling.
"""

from __future__ import annotations

import logging
import queue
import threading
from xml.etree.ElementTree import fromstring

import websocket

from soundtouch.api import NOTIFY_PORT
from soundtouch.models import DspControls, LevelControls, NowPlaying, ToneControls, Volume

_LOGGER = logging.getLogger(__name__)

# Push element name -> (event name, model). Anything else is surfaced as a bare
# refresh hint so the client can re-read /api/state rather than guess.
_HANDLERS = {
    "volumeUpdated": ("volume", lambda e: Volume.from_xml(e.find("volume"))),
    "nowPlayingUpdated": ("now_playing", lambda e: NowPlaying.from_xml(e.find("nowPlaying"))),
    "audiodspcontrols": ("dsp", DspControls.from_xml),
    "audioproducttonecontrols": ("tone", ToneControls.from_xml),
    "audioproductlevelcontrols": ("levels", LevelControls.from_xml),
}


class NotificationBridge:
    """Maintains a WebSocket to the speaker and fans updates out to subscribers."""

    def __init__(self, host: str):
        self.host = host
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=50)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def _publish(self, event: str, data: dict) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait({"event": event, "data": data})
            except queue.Full:
                # A stalled browser tab must not block the bridge.
                _LOGGER.debug("dropping event for slow subscriber")

    def _on_message(self, _ws, message: str) -> None:
        try:
            root = fromstring(message)
        except Exception:
            return
        # Pushes arrive wrapped in <updates deviceID="...">; SoundTouchSdkInfo is a
        # handshake frame with no payload.
        if root.tag != "updates":
            return
        for child in root:
            handler = _HANDLERS.get(child.tag)
            if not handler:
                self._publish("refresh", {"reason": child.tag})
                continue
            name, parse = handler
            try:
                model = parse(child)
            except Exception:
                self._publish("refresh", {"reason": child.tag})
                continue
            from dataclasses import asdict

            self._publish(name, asdict(model))

    def _on_error(self, _ws, error) -> None:
        _LOGGER.warning("websocket error: %s", error)

    def _on_close(self, _ws, *_args) -> None:
        _LOGGER.info("websocket closed")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        url = f"ws://{self.host}:{NOTIFY_PORT}"
        self._ws = websocket.WebSocketApp(
            url,
            subprotocols=["gabbo"],
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        # run_forever reconnects on drop, so a speaker reboot heals itself.
        self._thread = threading.Thread(
            target=lambda: self._ws.run_forever(reconnect=5),
            name="gabbo-bridge",
            daemon=True,
        )
        self._thread.start()
        _LOGGER.info("gabbo bridge started -> %s", url)
