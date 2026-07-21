"""Parser tests against XML captured from a real SoundTouch 300 (values anonymised)."""

import unittest
from pathlib import Path
from xml.etree.ElementTree import fromstring

from soundtouch.models import (
    ControlLevel,
    DeviceInfo,
    DspControls,
    LevelControls,
    NowPlaying,
    Speakers,
    SourceList,
    ToneControls,
    Volume,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return fromstring((FIXTURES / f"{name}.xml").read_bytes())


class TestDeviceInfo(unittest.TestCase):
    def test_parses_identity(self):
        info = DeviceInfo.from_xml(load("info"))
        self.assertEqual(info.name, "Living Room")
        self.assertEqual(info.type, "SoundTouch 300")
        self.assertEqual(info.device_id, "A1B2C3D4E5F6")
        self.assertEqual(info.ip_address, "192.0.2.10")


class TestNowPlaying(unittest.TestCase):
    def test_parses_tv_source(self):
        np = NowPlaying.from_xml(load("now_playing"))
        self.assertEqual(np.source, "PRODUCT")
        self.assertEqual(np.source_account, "TV")
        self.assertTrue(np.is_playing)
        self.assertTrue(np.is_tv)

    def test_default_art_image_is_not_treated_as_art(self):
        # SHOW_DEFAULT_IMAGE means no real art; the element text must not become a URL.
        np = NowPlaying.from_xml(load("now_playing"))
        self.assertEqual(np.art_status, "SHOW_DEFAULT_IMAGE")
        self.assertEqual(np.art_url, "")

    def test_standby_is_detected(self):
        np = NowPlaying.from_xml(fromstring('<nowPlaying deviceID="X" source="STANDBY" />'))
        self.assertTrue(np.is_standby)
        self.assertFalse(np.is_invalid)

    def test_invalid_source_is_detected(self):
        # What any cloud-backed content collapses to post-shutdown.
        np = NowPlaying.from_xml(fromstring('<nowPlaying deviceID="X" source="INVALID_SOURCE" />'))
        self.assertTrue(np.is_invalid)
        self.assertFalse(np.is_standby)
        self.assertFalse(np.is_playing)

    def test_parses_streaming_track_metadata(self):
        xml = """<nowPlaying deviceID="X" source="SPOTIFY" sourceAccount="spotify_user">
            <ContentItem source="SPOTIFY" isPresetable="true"><itemName>Song</itemName></ContentItem>
            <track>Digital Love</track><artist>Daft Punk</artist><album>Discovery</album>
            <art artImageStatus="IMAGE_PRESENT">https://i.scdn.co/image/abc</art>
            <playStatus>PLAY_STATE</playStatus></nowPlaying>"""
        np = NowPlaying.from_xml(fromstring(xml))
        self.assertEqual(np.track, "Digital Love")
        self.assertEqual(np.artist, "Daft Punk")
        self.assertEqual(np.art_url, "https://i.scdn.co/image/abc")
        self.assertFalse(np.is_tv)


class TestVolume(unittest.TestCase):
    def test_parses_volume(self):
        vol = Volume.from_xml(load("volume"))
        self.assertEqual(vol.actual, 28)
        self.assertEqual(vol.target, 28)
        self.assertFalse(vol.muted)


class TestToneControls(unittest.TestCase):
    def test_parses_bass_range_from_device(self):
        tone = ToneControls.from_xml(load("audioproducttonecontrols"))
        self.assertEqual(tone.bass.value, 100)
        self.assertEqual(tone.bass.min_value, -100)
        self.assertEqual(tone.bass.max_value, 100)
        self.assertEqual(tone.bass.step, 25)

    def test_bass_has_nine_detents_like_the_remote(self):
        tone = ToneControls.from_xml(load("audioproducttonecontrols"))
        self.assertEqual(tone.bass.steps, [-100, -75, -50, -25, 0, 25, 50, 75, 100])

    def test_request_body_sends_only_value(self):
        tone = ToneControls.from_xml(load("audioproducttonecontrols"))
        body = tone.to_request_body(bass=50).decode()
        self.assertIn('<bass value="50"', body)
        self.assertIn('<treble value="0"', body)
        for rejected in ("minValue", "maxValue", "step"):
            self.assertNotIn(rejected, body)

    def test_request_body_preserves_untouched_channel(self):
        tone = ToneControls.from_xml(load("audioproducttonecontrols"))
        body = tone.to_request_body(treble=25).decode()
        self.assertIn('<bass value="100"', body)
        self.assertIn('<treble value="25"', body)


class TestControlLevelClamp(unittest.TestCase):
    def setUp(self):
        self.level = ControlLevel(value=0, min_value=-100, max_value=100, step=25)

    def test_snaps_to_nearest_detent(self):
        self.assertEqual(self.level.clamp(60), 50)
        self.assertEqual(self.level.clamp(-10), 0)

    def test_clamps_out_of_range(self):
        self.assertEqual(self.level.clamp(500), 100)
        self.assertEqual(self.level.clamp(-500), -100)

    def test_exact_detent_is_unchanged(self):
        self.assertEqual(self.level.clamp(75), 75)


class TestLevelControls(unittest.TestCase):
    def test_parses_speaker_levels(self):
        levels = LevelControls.from_xml(load("audioproductlevelcontrols"))
        self.assertEqual(levels.center.value, -10)
        self.assertEqual(levels.surround.value, 10)
        self.assertEqual(levels.center.step, 10)

    def test_request_body_uses_device_element_names(self):
        levels = LevelControls.from_xml(load("audioproductlevelcontrols"))
        body = levels.to_request_body(center=20).decode()
        self.assertIn('<frontCenterSpeakerLevel value="20"', body)
        self.assertIn('<rearSurroundSpeakersLevel value="10"', body)


class TestDspControls(unittest.TestCase):
    def test_parses_audio_mode(self):
        dsp = DspControls.from_xml(load("audiodspcontrols"))
        self.assertEqual(dsp.audio_mode, "AUDIO_MODE_NORMAL")
        self.assertFalse(dsp.dialog_enabled)
        self.assertEqual(dsp.supported_modes, ["AUDIO_MODE_NORMAL", "AUDIO_MODE_DIALOG"])

    def test_request_body(self):
        body = DspControls.to_request_body("AUDIO_MODE_DIALOG").decode()
        self.assertIn('audiomode="AUDIO_MODE_DIALOG"', body)
        self.assertNotIn("supportedaudiomodes", body)

    def test_supported_mode_is_applicable(self):
        dsp = DspControls.from_xml(load("audiodspcontrols"))
        self.assertTrue(dsp.is_applicable)

    def test_direct_mode_is_not_applicable(self):
        # Non-TV sources report AUDIO_MODE_DIRECT, which the device won't accept as a
        # write and doesn't list -- the toggle must show as not-in-effect, not broken.
        xml = '<audiodspcontrols audiomode="AUDIO_MODE_DIRECT" supportedaudiomodes="AUDIO_MODE_NORMAL|AUDIO_MODE_DIALOG" />'
        dsp = DspControls.from_xml(fromstring(xml))
        self.assertFalse(dsp.is_applicable)
        self.assertFalse(dsp.dialog_enabled)


class TestSpeakers(unittest.TestCase):
    def test_parses_sub_and_surrounds(self):
        speakers = Speakers.from_xml(load("audiospeakerattributeandsetting"))
        names = {s.name for s in speakers.items}
        self.assertEqual(names, {"rear", "subwoofer01"})
        self.assertTrue(all(s.available and s.active and s.wireless for s in speakers.items))

    def test_toggle_request_body_sends_only_active(self):
        # The device rejects available/wireless/controllable; only bare active is accepted.
        body = Speakers.to_request_body("rear", False).decode()
        self.assertIn('<rear active="false"', body)
        for rejected in ("available", "wireless", "controllable"):
            self.assertNotIn(rejected, body)

    def test_toggle_request_body_true(self):
        body = Speakers.to_request_body("subwoofer01", True).decode()
        self.assertIn('<subwoofer01 active="true"', body)


class TestSources(unittest.TestCase):
    def test_tv_is_the_ready_source(self):
        sources = SourceList.from_xml(load("sources"))
        ready = {s.key for s in sources.items if s.is_ready}
        self.assertIn("PRODUCT/TV", ready)

    def test_selectable_excludes_streaming_sources(self):
        sources = SourceList.from_xml(load("sources"))
        keys = {s.key for s in sources.selectable()}
        self.assertIn("PRODUCT/TV", keys)
        self.assertIn("PRODUCT/HDMI_1", keys)
        self.assertIn("BLUETOOTH", keys)
        self.assertFalse(any(k.startswith("SPOTIFY") for k in keys))
        self.assertFalse(any(k.startswith("AIRPLAY") for k in keys))

    def test_selectable_dedupes_repeated_sources(self):
        # The speaker has been observed returning the same source many times in one
        # response under heavy concurrent connection load.
        xml = """<sources deviceID="X">
            <sourceItem source="PRODUCT" sourceAccount="TV" status="READY" isLocal="true" />
            <sourceItem source="PRODUCT" sourceAccount="TV" status="UNAVAILABLE" isLocal="true" />
            <sourceItem source="PRODUCT" sourceAccount="TV" status="UNAVAILABLE" isLocal="true" />
            <sourceItem source="BLUETOOTH" status="UNAVAILABLE" isLocal="true" />
            <sourceItem source="BLUETOOTH" status="UNAVAILABLE" isLocal="true" />
        </sources>"""
        sources = SourceList.from_xml(fromstring(xml))
        selectable = sources.selectable()
        keys = [s.key for s in selectable]
        self.assertEqual(keys.count("PRODUCT/TV"), 1)
        self.assertEqual(keys.count("BLUETOOTH"), 1)

    def test_selectable_prefers_ready_duplicate_over_earlier_unavailable_one(self):
        xml = """<sources deviceID="X">
            <sourceItem source="PRODUCT" sourceAccount="TV" status="UNAVAILABLE" isLocal="true" />
            <sourceItem source="PRODUCT" sourceAccount="TV" status="READY" isLocal="true" />
        </sources>"""
        sources = SourceList.from_xml(fromstring(xml))
        (tv,) = [s for s in sources.selectable() if s.key == "PRODUCT/TV"]
        self.assertTrue(tv.is_ready)


if __name__ == "__main__":
    unittest.main()
