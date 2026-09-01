"""Tests for soundcloud_ma_provider.SoundCloudProvider."""

from __future__ import annotations

import importlib.metadata
from unittest.mock import MagicMock, patch

import pytest
from music_assistant_models.enums import MediaType, ProviderFeature
from music_assistant_models.errors import MediaNotFoundError, ProviderUnavailableError
from music_assistant_models.media_items import BrowseFolder, Playlist, SearchResults, Track
from music_assistant_models.streamdetails import StreamDetails

import soundcloud_ma_provider as scm

TRACK = {
    "url": "https://soundcloud.com/burial/archangel",
    "title": "Archangel",
    "artist": "Burial",
    "artist_url": "https://soundcloud.com/burial",
    "duration": 245000,
    "image": "https://i1.sndcdn.com/archangel.jpg",
}

ARTIST = {
    "url": "https://soundcloud.com/burial",
    "artist_url": "https://soundcloud.com/burial",
    "artist": "Burial",
    "image": "https://i1.sndcdn.com/burial.jpg",
}

PLAYLIST = {
    "url": "https://soundcloud.com/burial/sets/untrue",
    "title": "Untrue",
    "artist": "Burial",
    "image": "https://i1.sndcdn.com/untrue.jpg",
}


# --------------------------------------------------------------------------
# handle_async_init / entry point
# --------------------------------------------------------------------------


class TestInit:
    async def test_handle_async_init_lazily_imports_client(self, provider):
        fake_client = MagicMock()
        with patch("nuvem_de_som.SoundCloudAPI", return_value=fake_client) as ctor:
            await provider.handle_async_init()
        ctor.assert_called_once()
        assert provider._client is fake_client

    async def test_handle_async_init_missing_dependency_raises_provider_unavailable(
        self, provider
    ):
        with patch("nuvem_de_som.SoundCloudAPI", side_effect=ImportError("nope")):
            with pytest.raises(ProviderUnavailableError):
                await provider.handle_async_init()

    def test_entry_point_resolves_to_module(self):
        eps = importlib.metadata.entry_points(group="music_assistant.provider")
        matches = [ep for ep in eps if ep.name == "soundcloud_free"]
        assert len(matches) == 1
        loaded = matches[0].load()
        assert loaded is scm


# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------


class TestSearch:
    async def test_search_maps_all_media_types_to_search_results(self, provider):
        provider._client = MagicMock()
        provider._client.search_tracks.return_value = iter([TRACK])
        provider._client.search_people.return_value = iter([ARTIST])
        provider._client.search_sets.return_value = iter([PLAYLIST])

        result = await provider.search(
            "burial", [MediaType.TRACK, MediaType.ARTIST, MediaType.PLAYLIST], limit=5
        )

        assert isinstance(result, SearchResults)
        assert len(result.tracks) == 1
        assert result.tracks[0].name == "Archangel"
        assert result.tracks[0].duration == 245000
        assert len(result.artists) == 1
        assert result.artists[0].name == "Burial"
        assert len(result.playlists) == 1
        assert result.playlists[0].name == "Untrue"

        provider._client.search_tracks.assert_called_once_with("burial", limit=5)
        provider._client.search_people.assert_called_once_with("burial", limit=5)
        provider._client.search_sets.assert_called_once_with("burial", limit=5)

    async def test_search_only_requested_media_type_is_queried(self, provider):
        provider._client = MagicMock()
        provider._client.search_tracks.return_value = iter([TRACK])

        result = await provider.search("burial", [MediaType.TRACK], limit=10)

        assert len(result.tracks) == 1
        assert result.artists == []
        assert result.playlists == []
        provider._client.search_people.assert_not_called()
        provider._client.search_sets.assert_not_called()


# --------------------------------------------------------------------------
# browse
# --------------------------------------------------------------------------


class TestBrowse:
    async def test_browse_root_returns_popular_folder(self, provider):
        provider._client = MagicMock()
        result = await provider.browse("soundcloud_free://")
        assert len(result) == 1
        assert isinstance(result[0], BrowseFolder)
        assert result[0].item_id == "popular"

    async def test_browse_into_folder_returns_tracks(self, provider):
        provider._client = MagicMock()
        provider._client.search_tracks.return_value = iter([TRACK])

        result = await provider.browse("soundcloud_free://popular")

        assert len(result) == 1
        assert isinstance(result[0], Track)
        provider._client.search_tracks.assert_called_once_with("trending soundcloud", limit=20)

    def test_browse_feature_flag_is_declared(self):
        assert ProviderFeature.BROWSE in scm.SUPPORTED_FEATURES


# --------------------------------------------------------------------------
# get_track / get_artist
# --------------------------------------------------------------------------


class TestGetArtist:
    async def test_get_artist_happy_path(self, provider):
        provider._client = MagicMock()
        provider._client.resolve_user.return_value = ARTIST

        artist = await provider.get_artist("https://soundcloud.com/burial")

        assert artist.name == "Burial"
        provider._client.resolve_user.assert_called_once_with("https://soundcloud.com/burial")

    async def test_get_artist_upstream_miss_falls_back_to_slug_stub(self, provider):
        provider._client = MagicMock()
        provider._client.resolve_user.return_value = None

        artist = await provider.get_artist("https://soundcloud.com/some-dj")

        assert artist.name == "Some Dj"
        assert artist.item_id == "https://soundcloud.com/some-dj"


class TestGetTrack:
    async def test_get_track_returns_slug_stub(self, provider):
        track = await provider.get_track("https://soundcloud.com/burial/archangel")
        assert track.name == "Archangel"
        assert track.item_id == "https://soundcloud.com/burial/archangel"


# --------------------------------------------------------------------------
# get_playlist
# --------------------------------------------------------------------------


class TestGetPlaylist:
    async def test_get_playlist_returns_slug_stub_for_set_url(self, provider):
        playlist = await provider.get_playlist("https://soundcloud.com/burial/sets/untrue")
        assert isinstance(playlist, Playlist)
        assert playlist.name == "Untrue"
        assert playlist.item_id == "https://soundcloud.com/burial/sets/untrue"

    async def test_get_playlist_raises_media_not_found_for_non_set_uri(self, provider):
        with pytest.raises(MediaNotFoundError):
            await provider.get_playlist("https://soundcloud.com/burial")

    async def test_search_result_playlist_round_trips_through_get_playlist(self, provider):
        # A playlist returned by search() must stay openable: get_playlist() on
        # its uri returns a Playlist, and get_playlist_tracks() on the same uri
        # still resolves real tracks.
        provider._client = MagicMock()
        provider._client.search_sets.return_value = iter([PLAYLIST])
        search_result = await provider.search("burial", [MediaType.PLAYLIST], limit=5)
        found = search_result.playlists[0]

        playlist = await provider.get_playlist(found.item_id)
        assert isinstance(playlist, Playlist)
        assert playlist.item_id == found.item_id

        provider._client.get_tracks.return_value = iter([TRACK])
        tracks = await provider.get_playlist_tracks(found.item_id)
        assert len(tracks) == 1
        assert tracks[0].name == "Archangel"

    async def test_get_playlist_tracks_still_works_independently(self, provider):
        provider._client = MagicMock()
        provider._client.get_tracks.return_value = iter([TRACK])

        tracks = await provider.get_playlist_tracks(
            "https://soundcloud.com/burial/sets/untrue"
        )

        assert len(tracks) == 1
        assert tracks[0].name == "Archangel"


# --------------------------------------------------------------------------
# get_stream_details
# --------------------------------------------------------------------------


class TestGetStreamDetails:
    async def test_get_stream_details_http(self, provider):
        provider._client = MagicMock()
        provider._client.resolve_stream.return_value = "https://cf-media.sndcdn.com/x.128.mp3"

        details = await provider.get_stream_details(
            "https://soundcloud.com/burial/archangel", MediaType.TRACK
        )

        assert isinstance(details, StreamDetails)
        assert details.path == "https://cf-media.sndcdn.com/x.128.mp3"

    async def test_get_stream_details_hls(self, provider):
        from music_assistant_models.enums import StreamType

        provider._client = MagicMock()
        provider._client.resolve_stream.return_value = "https://cf-hls-media.sndcdn.com/x.m3u8"

        details = await provider.get_stream_details(
            "https://soundcloud.com/burial/archangel", MediaType.TRACK
        )

        assert details.stream_type == StreamType.HLS

    async def test_get_stream_details_upstream_miss_raises_media_not_found(self, provider):
        provider._client = MagicMock()
        provider._client.resolve_stream.return_value = None

        with pytest.raises(MediaNotFoundError):
            await provider.get_stream_details(
                "https://soundcloud.com/burial/archangel", MediaType.TRACK
            )
