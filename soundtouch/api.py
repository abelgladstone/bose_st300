"""HTTP client for the SoundTouch local webservices API (port 8090)."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from urllib.parse import urlparse
from xml.etree.ElementTree import Element, SubElement, fromstring, tostring

import requests

from soundtouch.album_art import AlbumArtLookup
from soundtouch.models import (
    DeviceInfo,
    DspControls,
    LevelControls,
    NowPlaying,
    Speakers,
    SourceList,
    ToneControls,
    Volume,
)

_LOGGER = logging.getLogger(__name__)

API_PORT = 8090
NOTIFY_PORT = 8080

# The sender name the official app uses; the device ignores unknown senders on /key.
SENDER = "Gabbo"

KEYS = {
    "PLAY_PAUSE",
    "NEXT_TRACK",
    "PREV_TRACK",
    "POWER",
    "MUTE",
    "VOLUME_UP",
    "VOLUME_DOWN",
}


class SoundTouchError(RuntimeError):
    pass


@dataclass
class State:
    """Everything the UI needs, in one snapshot."""

    info: DeviceInfo
    now_playing: NowPlaying
    volume: Volume
    tone: ToneControls
    levels: LevelControls
    dsp: DspControls
    speakers: Speakers
    sources: SourceList

    def to_dict(self) -> dict:
        data = asdict(self)
        data["now_playing"]["is_playing"] = self.now_playing.is_playing
        data["now_playing"]["is_tv"] = self.now_playing.is_tv
        data["now_playing"]["is_standby"] = self.now_playing.is_standby
        data["now_playing"]["is_invalid"] = self.now_playing.is_invalid
        data["dsp"]["dialog_enabled"] = self.dsp.dialog_enabled
        data["dsp"]["is_applicable"] = self.dsp.is_applicable
        data["sources"]["selectable"] = [
            {**asdict(s), "key": s.key, "is_ready": s.is_ready} for s in self.sources.selectable()
        ]
        for group in ("tone", "levels"):
            for control in data[group].values():
                control["steps"] = None  # computed client-side from min/max/step
        return data


class SoundTouchClient:
    def __init__(self, host: str, timeout: float = 5.0, album_art: AlbumArtLookup | None = None):
        self.host = host
        self.timeout = timeout
        self._session = requests.Session()
        self._album_art = album_art or AlbumArtLookup()

    def _url(self, path: str) -> str:
        return f"http://{self.host}:{API_PORT}/{path.lstrip('/')}"

    def get(self, path: str) -> Element:
        try:
            response = self._session.get(self._url(path), timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as err:
            raise SoundTouchError(f"GET /{path} failed: {err}") from err
        return fromstring(response.content)

    def post(self, path: str, body: bytes) -> Element | None:
        try:
            response = self._session.post(self._url(path), data=body, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as err:
            raise SoundTouchError(f"POST /{path} failed: {err}") from err

        content = response.content.strip()
        if not content:
            return None
        try:
            elm = fromstring(content)
        except Exception:
            _LOGGER.debug("POST /%s returned non-XML: %r", path, content[:200])
            return None
        # The device answers errors with HTTP 200 and an <errors> body.
        if elm.tag == "errors":
            raise SoundTouchError(f"POST /{path} rejected: {tostring(elm).decode()}")
        return elm

    # --- reads -------------------------------------------------------------

    def info(self) -> DeviceInfo:
        return DeviceInfo.from_xml(self.get("info"))

    def now_playing(self) -> NowPlaying:
        return self._enrich_art(NowPlaying.from_xml(self.get("now_playing")))

    def _enrich_art(self, now_playing: NowPlaying) -> NowPlaying:
        """Fill in art_url from an external lookup when the device has none.

        AirPlay in particular reports no art at all; other sources may too. Only
        ever used when the device itself came back empty, and only for a confident
        match -- see AlbumArtLookup.
        """
        if now_playing.art_url or not (now_playing.artist or now_playing.track):
            return now_playing
        art_url = self._album_art.lookup(now_playing.artist, now_playing.track)
        if art_url:
            now_playing.art_url = art_url
        return now_playing

    def volume(self) -> Volume:
        return Volume.from_xml(self.get("volume"))

    def tone(self) -> ToneControls:
        return ToneControls.from_xml(self.get("audioproducttonecontrols"))

    def levels(self) -> LevelControls:
        return LevelControls.from_xml(self.get("audioproductlevelcontrols"))

    def dsp(self) -> DspControls:
        return DspControls.from_xml(self.get("audiodspcontrols"))

    def speakers(self) -> Speakers:
        return Speakers.from_xml(self.get("audiospeakerattributeandsetting"))

    def sources(self) -> SourceList:
        return SourceList.from_xml(self.get("sources"))

    def is_device_art(self, url: str) -> bool:
        """Whether a now_playing art_url is hosted on the speaker itself.

        The speaker only accepts connections from its own subnet (see
        bose_soundtouch_relay's FINDINGS.md), so a browser off that subnet can't load
        such a URL directly -- it must be proxied through this server, which does sit
        on the speaker's network. Externally-hosted art (e.g. the iTunes fallback) is
        already reachable from any browser and must not be proxied.
        """
        return bool(url) and urlparse(url).hostname == self.host

    def fetch_art(self, url: str) -> tuple[bytes, str]:
        if not self.is_device_art(url):
            raise SoundTouchError("refusing to proxy non-device art url")
        try:
            response = self._session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as err:
            raise SoundTouchError(f"GET art failed: {err}") from err
        return response.content, response.headers.get("Content-Type", "image/jpeg")

    def state(self) -> State:
        return State(
            info=self.info(),
            now_playing=self.now_playing(),
            volume=self.volume(),
            tone=self.tone(),
            levels=self.levels(),
            dsp=self.dsp(),
            speakers=self.speakers(),
            sources=self.sources(),
        )

    # --- writes ------------------------------------------------------------

    def set_volume(self, value: int) -> None:
        value = max(0, min(100, int(value)))
        root = Element("volume")
        root.text = str(value)
        self.post("volume", tostring(root))

    def press_key(self, key: str) -> None:
        """Send a key. A press must be followed by a release or the device ignores it."""
        if key not in KEYS:
            raise SoundTouchError(f"unknown key: {key}")
        for state in ("press", "release"):
            root = Element("key", state=state, sender=SENDER)
            root.text = key
            self.post("key", tostring(root))

    def select_source(self, source: str, source_account: str = "") -> None:
        attrs = {"source": source}
        if source_account:
            attrs["sourceAccount"] = source_account
        self.post("select", tostring(Element("ContentItem", **attrs)))

    def set_tone(self, bass: int | None = None, treble: int | None = None) -> ToneControls:
        current = self.tone()
        self.post("audioproducttonecontrols", current.to_request_body(bass=bass, treble=treble))
        return self.tone()

    def set_levels(self, center: int | None = None, surround: int | None = None) -> LevelControls:
        current = self.levels()
        self.post("audioproductlevelcontrols", current.to_request_body(center=center, surround=surround))
        return self.levels()

    def set_audio_mode(self, audio_mode: str) -> DspControls:
        current = self.dsp()
        if current.supported_modes and audio_mode not in current.supported_modes:
            raise SoundTouchError(f"unsupported audio mode: {audio_mode}")
        self.post("audiodspcontrols", DspControls.to_request_body(audio_mode))
        return self.dsp()

    def set_name(self, name: str) -> DeviceInfo:
        name = (name or "").strip()
        if not name:
            raise SoundTouchError("name cannot be empty")
        root = Element("name")
        root.text = name
        self.post("name", tostring(root))
        return self.info()

    def set_speaker_active(self, name: str, active: bool) -> Speakers:
        speakers = self.speakers()
        if name not in {s.name for s in speakers.items}:
            raise SoundTouchError(f"unknown speaker: {name}")
        self.post("audiospeakerattributeandsetting", Speakers.to_request_body(name, active))
        return self.speakers()
