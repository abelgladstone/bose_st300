"""Unit tests for the iTunes fallback album art lookup."""

import unittest
from unittest.mock import MagicMock, patch

import requests

from soundtouch.album_art import AlbumArtLookup


def _response(payload):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload
    return resp


class TestAlbumArtLookup(unittest.TestCase):
    def test_confident_match_returns_upsized_artwork(self):
        lookup = AlbumArtLookup()
        payload = {
            "results": [
                {
                    "artistName": "Daft Punk",
                    "trackName": "Digital Love",
                    "artworkUrl100": "https://example.com/art/100x100bb.jpg",
                }
            ]
        }
        with patch.object(lookup._session, "get", return_value=_response(payload)) as mock_get:
            art_url = lookup.lookup("Daft Punk", "Digital Love")
        self.assertEqual(art_url, "https://example.com/art/600x600bb.jpg")
        mock_get.assert_called_once()

    def test_no_matching_result_returns_blank(self):
        lookup = AlbumArtLookup()
        payload = {
            "results": [
                {
                    "artistName": "Some Cover Band",
                    "trackName": "Totally Different Song",
                    "artworkUrl100": "https://example.com/art/100x100bb.jpg",
                }
            ]
        }
        with patch.object(lookup._session, "get", return_value=_response(payload)):
            art_url = lookup.lookup("Daft Punk", "Digital Love")
        self.assertEqual(art_url, "")

    def test_empty_results_returns_blank(self):
        lookup = AlbumArtLookup()
        with patch.object(lookup._session, "get", return_value=_response({"results": []})):
            art_url = lookup.lookup("Daft Punk", "Digital Love")
        self.assertEqual(art_url, "")

    def test_request_exception_returns_blank(self):
        lookup = AlbumArtLookup()
        with patch.object(lookup._session, "get", side_effect=requests.RequestException("boom")):
            art_url = lookup.lookup("Daft Punk", "Digital Love")
        self.assertEqual(art_url, "")

    def test_empty_artist_and_track_skips_request(self):
        lookup = AlbumArtLookup()
        with patch.object(lookup._session, "get") as mock_get:
            art_url = lookup.lookup("", "")
        self.assertEqual(art_url, "")
        mock_get.assert_not_called()

    def test_cache_hit_avoids_second_request(self):
        lookup = AlbumArtLookup()
        payload = {
            "results": [
                {
                    "artistName": "Daft Punk",
                    "trackName": "Digital Love",
                    "artworkUrl100": "https://example.com/art/100x100bb.jpg",
                }
            ]
        }
        with patch.object(lookup._session, "get", return_value=_response(payload)) as mock_get:
            lookup.lookup("Daft Punk", "Digital Love")
            lookup.lookup("Daft Punk", "Digital Love")
        mock_get.assert_called_once()

    def test_negative_result_is_also_cached(self):
        lookup = AlbumArtLookup()
        with patch.object(
            lookup._session, "get", return_value=_response({"results": []})
        ) as mock_get:
            lookup.lookup("Daft Punk", "Digital Love")
            lookup.lookup("Daft Punk", "Digital Love")
        mock_get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
