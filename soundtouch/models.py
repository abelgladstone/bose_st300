"""Dataclasses mapping the SoundTouch XML responses.

Each model parses from an xml.etree Element and, where the device accepts writes,
serialises back to a request body. Set-endpoints echo only the `value` attribute --
sending minValue/maxValue/step back is rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.etree.ElementTree import Element, SubElement, tostring


def _int(value: str | None, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool(value: str | None) -> bool:
    return str(value).lower() == "true"


@dataclass
class DeviceInfo:
    device_id: str = ""
    name: str = ""
    type: str = ""
    ip_address: str = ""

    @classmethod
    def from_xml(cls, elm: Element) -> "DeviceInfo":
        network = elm.find(".//networkInfo")
        return cls(
            device_id=elm.get("deviceID", ""),
            name=elm.findtext("name", ""),
            type=elm.findtext("type", ""),
            ip_address=network.findtext("ipAddress", "") if network is not None else "",
        )


@dataclass
class NowPlaying:
    source: str = ""
    source_account: str = ""
    play_status: str = ""
    track: str = ""
    artist: str = ""
    album: str = ""
    station: str = ""
    art_url: str = ""
    art_status: str = ""

    @property
    def is_playing(self) -> bool:
        return self.play_status == "PLAY_STATE"

    @property
    def is_tv(self) -> bool:
        """TV/HDMI audio carries no track metadata, so the UI shows a source card."""
        return self.source == "PRODUCT"

    @property
    def is_standby(self) -> bool:
        """The speaker reports standby as a now_playing source rather than a power field."""
        return self.source == "STANDBY"

    @property
    def is_invalid(self) -> bool:
        """The speaker could not resolve the requested content.

        Since the Bose cloud shutdown this is what any cloud-backed content (presets,
        TuneIn stations, stored Spotify containers) collapses to: the device accepts
        the selection, fails to resolve it upstream, and lands on INVALID_SOURCE.
        """
        return self.source == "INVALID_SOURCE"

    @classmethod
    def from_xml(cls, elm: Element) -> "NowPlaying":
        art = elm.find("art")
        art_url = ""
        art_status = ""
        if art is not None:
            art_status = art.get("artImageStatus", "")
            # SHOW_DEFAULT_IMAGE means there is no real art, just a placeholder.
            if art_status == "IMAGE_PRESENT":
                art_url = (art.text or "").strip()
        return cls(
            source=elm.get("source", ""),
            source_account=elm.get("sourceAccount", ""),
            play_status=elm.findtext("playStatus", ""),
            track=elm.findtext("track", ""),
            artist=elm.findtext("artist", ""),
            album=elm.findtext("album", ""),
            station=elm.findtext("stationName", ""),
            art_url=art_url,
            art_status=art_status,
        )


@dataclass
class Volume:
    target: int = 0
    actual: int = 0
    muted: bool = False

    @classmethod
    def from_xml(cls, elm: Element) -> "Volume":
        return cls(
            target=_int(elm.findtext("targetvolume")),
            actual=_int(elm.findtext("actualvolume")),
            muted=_bool(elm.findtext("muteenabled")),
        )


@dataclass
class ControlLevel:
    """A value with its allowed range, as the device reports it.

    The ST300 exposes bass, treble and speaker levels this way. min/max/step come
    from the device rather than being hardcoded, so the UI renders the real detents.
    """

    name: str = ""
    value: int = 0
    min_value: int = 0
    max_value: int = 0
    step: int = 1

    @classmethod
    def from_xml(cls, elm: Element) -> "ControlLevel":
        return cls(
            name=elm.tag,
            value=_int(elm.get("value")),
            min_value=_int(elm.get("minValue")),
            max_value=_int(elm.get("maxValue")),
            step=_int(elm.get("step"), 1),
        )

    @property
    def steps(self) -> list[int]:
        return list(range(self.min_value, self.max_value + 1, self.step or 1))

    def clamp(self, value: int) -> int:
        """Snap to the nearest legal detent; the device rejects off-step values."""
        value = max(self.min_value, min(self.max_value, int(value)))
        step = self.step or 1
        offset = value - self.min_value
        return self.min_value + round(offset / step) * step


@dataclass
class ToneControls:
    bass: ControlLevel = field(default_factory=ControlLevel)
    treble: ControlLevel = field(default_factory=ControlLevel)

    @classmethod
    def from_xml(cls, elm: Element) -> "ToneControls":
        return cls(
            bass=ControlLevel.from_xml(elm.find("bass")),
            treble=ControlLevel.from_xml(elm.find("treble")),
        )

    def to_request_body(self, bass: int | None = None, treble: int | None = None) -> bytes:
        root = Element("audioproducttonecontrols")
        SubElement(root, "bass", value=str(self.bass.clamp(bass if bass is not None else self.bass.value)))
        SubElement(root, "treble", value=str(self.treble.clamp(treble if treble is not None else self.treble.value)))
        return tostring(root)


@dataclass
class LevelControls:
    center: ControlLevel = field(default_factory=ControlLevel)
    surround: ControlLevel = field(default_factory=ControlLevel)

    @classmethod
    def from_xml(cls, elm: Element) -> "LevelControls":
        return cls(
            center=ControlLevel.from_xml(elm.find("frontCenterSpeakerLevel")),
            surround=ControlLevel.from_xml(elm.find("rearSurroundSpeakersLevel")),
        )

    def to_request_body(self, center: int | None = None, surround: int | None = None) -> bytes:
        root = Element("audioproductlevelcontrols")
        SubElement(
            root,
            "frontCenterSpeakerLevel",
            value=str(self.center.clamp(center if center is not None else self.center.value)),
        )
        SubElement(
            root,
            "rearSurroundSpeakersLevel",
            value=str(self.surround.clamp(surround if surround is not None else self.surround.value)),
        )
        return tostring(root)


@dataclass
class DspControls:
    audio_mode: str = ""
    supported_modes: list[str] = field(default_factory=list)
    video_sync_delay: int = 0

    @classmethod
    def from_xml(cls, elm: Element) -> "DspControls":
        supported = elm.get("supportedaudiomodes", "")
        return cls(
            audio_mode=elm.get("audiomode", ""),
            supported_modes=[m for m in supported.split("|") if m],
            video_sync_delay=_int(elm.get("videosyncaudiodelay")),
        )

    @property
    def dialog_enabled(self) -> bool:
        return self.audio_mode == "AUDIO_MODE_DIALOG"

    @property
    def is_applicable(self) -> bool:
        """Whether the speech-mode toggle applies to what is playing right now.

        On non-TV sources the device reports AUDIO_MODE_DIRECT -- a mode it does not
        list in supportedaudiomodes and will not accept as a write. Neither Normal nor
        Dialog is in effect then, so the UI must not claim one is.
        """
        return self.audio_mode in self.supported_modes

    @staticmethod
    def to_request_body(audio_mode: str) -> bytes:
        return tostring(Element("audiodspcontrols", audiomode=audio_mode))


@dataclass
class Speaker:
    name: str = ""
    available: bool = False
    active: bool = False
    wireless: bool = False
    controllable: bool = False


@dataclass
class Speakers:
    """Accessory speakers (surrounds, bass module) and their on/off state.

    `active` is the only writable attribute, and only on its own: a request body of
    <name active="true|false"/> is accepted, but including available/wireless/controllable
    is rejected as Invalid Input. The other flags are read-only status.
    """

    items: list[Speaker] = field(default_factory=list)

    @classmethod
    def from_xml(cls, elm: Element) -> "Speakers":
        return cls(
            items=[
                Speaker(
                    name=child.tag,
                    available=_bool(child.get("available")),
                    active=_bool(child.get("active")),
                    wireless=_bool(child.get("wireless")),
                    controllable=_bool(child.get("controllable")),
                )
                for child in elm
            ]
        )

    @staticmethod
    def to_request_body(name: str, active: bool) -> bytes:
        root = Element("audiospeakerattributeandsetting")
        SubElement(root, name, active=str(bool(active)).lower())
        return tostring(root)


@dataclass
class Source:
    source: str = ""
    source_account: str = ""
    status: str = ""
    is_local: bool = False
    display_name: str = ""

    @property
    def key(self) -> str:
        return f"{self.source}/{self.source_account}" if self.source_account else self.source

    @property
    def is_ready(self) -> bool:
        return self.status == "READY"

    @classmethod
    def from_xml(cls, elm: Element) -> "Source":
        return cls(
            source=elm.get("source", ""),
            source_account=elm.get("sourceAccount", ""),
            status=elm.get("status", ""),
            is_local=_bool(elm.get("isLocal")),
            display_name=(elm.text or "").strip(),
        )


@dataclass
class SourceList:
    items: list[Source] = field(default_factory=list)

    @classmethod
    def from_xml(cls, elm: Element) -> "SourceList":
        return cls(items=[Source.from_xml(child) for child in elm.findall("sourceItem")])

    def selectable(self) -> list[Source]:
        """Sources worth showing as buttons.

        Streaming sources (Spotify, AirPlay) are excluded: post-cloud-shutdown they
        arrive via Spotify Connect / AirPlay, which the speaker switches to on its own
        when a phone pushes audio. There is nothing useful to select here.

        The speaker has been observed returning the same source repeated dozens of
        times in one /sources response (seen after heavy concurrent connection
        activity) -- dedupe by key, keeping the first occurrence unless a later
        duplicate is READY and the one seen so far isn't.
        """
        selectable_keys = {"PRODUCT/TV", "PRODUCT/HDMI_1", "BLUETOOTH"}
        by_key: dict[str, Source] = {}
        for item in self.items:
            if item.key not in selectable_keys:
                continue
            existing = by_key.get(item.key)
            if existing is None or (item.is_ready and not existing.is_ready):
                by_key[item.key] = item
        return list(by_key.values())
