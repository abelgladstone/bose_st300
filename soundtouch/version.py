"""Single source of truth for the app version and release notes.

Surfaced by the /api/about endpoint and the UI's About dialog. Keep the top entry's
version in sync with pyproject.toml and the git release tag.
"""

__version__ = "0.0.3"

RELEASE_NOTES = [
    {
        "version": "0.0.3",
        "date": "2026-07-21",
        "title": "Album art fixes",
        "notes": [
            "Album art for AirPlay now shows up: when the device has none, look it "
            "up on iTunes, but only on a confident artist/track match.",
            "Fixed device-hosted album art not loading in the browser — it's now "
            "proxied through the server instead of linking to the speaker directly, "
            "which only the server (not the browser) can reach.",
            "Source list no longer shows duplicate buttons when the speaker repeats "
            "entries in its /sources response.",
        ],
    },
    {
        "version": "0.0.2",
        "date": "2026-07-18",
        "title": "Theming & polish",
        "notes": [
            "Light / dark theme (Catppuccin) with a toggle, remembered per device.",
            "Reorganised layout: Now Playing (with transport), Volume, Source, then the rest.",
            "Transport controls hide in standby — nothing to control when it's asleep.",
            "Rename the speaker directly from the app.",
            "About dialog with version and release notes.",
            "Fixed the bass/treble fill so it reaches the end at ±100.",
        ],
    },
    {
        "version": "0.0.1",
        "date": "2026-07-18",
        "title": "First release",
        "notes": [
            "Local web remote for the Bose SoundTouch 300 — replaces the Bose app "
            "retired when the SoundTouch cloud shut down.",
            "Volume, mute, power and transport controls.",
            "Bipolar bass & treble, and per-speaker level trims (centre / surround).",
            "Enable or disable the surround speakers and bass module.",
            "Speech mode (Normal / Dialog) for TV audio.",
            "Source switching — TV, HDMI, Bluetooth.",
            "Live now-playing with album art, updated in real time.",
            "Rename the speaker directly from the app.",
            "Runs containerised behind a reverse proxy under /bose.",
        ],
    },
]
