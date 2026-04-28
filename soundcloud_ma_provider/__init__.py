"""SoundCloud provider for Music Assistant via nuvem_de_som."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING

from music_assistant_models.enums import (
    ContentType,
    ImageType,
    MediaType,
    ProviderFeature,
    StreamType,
)
from music_assistant_models.errors import MediaNotFoundError, ProviderUnavailableError
from music_assistant_models.media_items import (
    Artist,
    AudioFormat,
    BrowseFolder,
    ItemMapping,
    MediaItemImage,
    MediaItemType,
    Playlist,
    ProviderMapping,
    SearchResults,
    Track,
    UniqueList,
)
from music_assistant_models.streamdetails import StreamDetails

from music_assistant.models.music_provider import MusicProvider

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ConfigEntry, ConfigValueType, ProviderConfig
    from music_assistant_models.provider import ProviderManifest
    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType

SUPPORTED_FEATURES = {
    ProviderFeature.SEARCH,
    ProviderFeature.ARTIST_TOPTRACKS,
}


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    return SoundCloudProvider(mass, manifest, config, SUPPORTED_FEATURES)


async def get_config_entries(
    mass: MusicAssistant,
    instance_id: str | None = None,
    action: str | None = None,
    values: dict[str, ConfigValueType] | None = None,
) -> tuple[ConfigEntry, ...]:
    return ()


def _image(url: str | None, instance_id: str) -> MediaItemImage | None:
    if not url:
        return None
    return MediaItemImage(type=ImageType.THUMB, path=url, provider=instance_id, remotely_accessible=True)



def _artist_mapping(name: str, domain: str, item_id: str | None = None) -> ItemMapping:
    resolved_id = item_id or name
    return ItemMapping(media_type=MediaType.ARTIST, item_id=resolved_id, provider=domain, name=name)


def _to_track(item: dict, domain: str, instance_id: str) -> Track:
    page_url = item.get("url", "")
    track = Track(
        item_id=page_url,
        provider=domain,
        name=item.get("title") or page_url.split("/")[-1],
        provider_mappings={
            ProviderMapping(
                item_id=page_url,
                provider_domain=domain,
                provider_instance=instance_id,
                audio_format=AudioFormat(content_type=ContentType.AAC),
            )
        },
        duration=int(item["duration"]) if item.get("duration") else 0,
    )
    artist_name = item.get("artist") or "Unknown"
    artist_url = item.get("artist_url") or ""
    track.artists = UniqueList([_artist_mapping(artist_name, domain, item_id=artist_url)])
    img = _image(item.get("image"), instance_id)
    if img:
        track.metadata.images = UniqueList([img])
    return track


def _to_artist(item: dict, domain: str, instance_id: str) -> Artist:
    url = item.get("artist_url") or item.get("url", "")
    artist = Artist(
        item_id=url,
        provider=domain,
        name=item.get("artist") or url.split("/")[-1],
        provider_mappings={
            ProviderMapping(item_id=url, provider_domain=domain, provider_instance=instance_id)
        },
    )
    img = _image(item.get("image"), instance_id)
    if img:
        artist.metadata.images = UniqueList([img])
    return artist


def _to_playlist(item: dict, domain: str, instance_id: str) -> Playlist:
    url = item.get("url", "")
    pl = Playlist(
        item_id=url,
        provider=domain,
        name=item.get("title") or url.split("/")[-1].replace("-", " ").title(),
        owner=item.get("artist") or "SoundCloud",
        is_editable=False,
        provider_mappings={
            ProviderMapping(item_id=url, provider_domain=domain, provider_instance=instance_id)
        },
    )
    img = _image(item.get("image"), instance_id)
    if img:
        pl.metadata.images = UniqueList([img])
    return pl


class SoundCloudProvider(MusicProvider):
    """Music Assistant provider for SoundCloud via nuvem_de_som."""

    @property
    def is_streaming_provider(self) -> bool:
        return True

    async def handle_async_init(self) -> None:
        try:
            from nuvem_de_som import SoundCloudAPI  # noqa: PLC0415
            self._client = SoundCloudAPI()
        except ImportError as err:
            raise ProviderUnavailableError("nuvem_de_som not installed") from err

    async def search(
        self, search_query: str, media_types: list[MediaType], limit: int = 10
    ) -> SearchResults:
        result = SearchResults()

        if MediaType.TRACK in media_types:
            items = await asyncio.to_thread(
                lambda: list(self._client.search_tracks(search_query, limit=limit))
            )
            result.tracks = [_to_track(i, self.domain, self.instance_id) for i in items]

        if MediaType.ARTIST in media_types:
            items = await asyncio.to_thread(
                lambda: list(self._client.search_people(search_query, limit=limit))
            )
            result.artists = [_to_artist(i, self.domain, self.instance_id) for i in items]

        if MediaType.PLAYLIST in media_types:
            items = await asyncio.to_thread(
                lambda: list(self._client.search_sets(search_query, limit=limit))
            )
            result.playlists = [_to_playlist(i, self.domain, self.instance_id) for i in items]

        return result

    async def browse(self, path: str) -> Sequence[MediaItemType | BrowseFolder]:
        parts = [p for p in path.split("://")[1].split("/") if p] if "://" in path else []
        if not parts:
            return [
                BrowseFolder(item_id="trending", provider=self.domain,
                             path=f"{path}/trending", name="Trending"),
            ]
        # "trending" folder — search the literal genre tag SoundCloud uses
        items = await asyncio.to_thread(
            lambda: list(self._client.search_tracks("trending soundcloud", limit=20))
        )
        return [_to_track(i, self.domain, self.instance_id) for i in items]

    async def get_artist(self, prov_artist_id: str) -> Artist:
        data = await asyncio.to_thread(self._client.resolve_user, prov_artist_id)
        if data:
            return _to_artist(data, self.domain, self.instance_id)
        # Fallback: stub from URL slug
        slug = prov_artist_id.rstrip("/").split("/")[-1]
        return Artist(
            item_id=prov_artist_id,
            provider=self.domain,
            name=slug.replace("-", " ").title(),
            provider_mappings={
                ProviderMapping(
                    item_id=prov_artist_id,
                    provider_domain=self.domain,
                    provider_instance=self.instance_id,
                )
            },
        )

    async def get_artist_toptracks(self, prov_artist_id: str) -> list[Track]:
        items = await asyncio.to_thread(
            lambda: list(self._client.get_tracks(prov_artist_id))
        )
        return [_to_track(i, self.domain, self.instance_id) for i in items]

    async def get_playlist(self, prov_playlist_id: str) -> Playlist:
        # Resolve title by re-searching — cheaper than fetching the playlist page
        return Playlist(
            item_id=prov_playlist_id,
            provider=self.domain,
            name=prov_playlist_id.rstrip("/").split("/")[-1].replace("-", " ").title(),
            owner="SoundCloud",
            is_editable=False,
            provider_mappings={
                ProviderMapping(
                    item_id=prov_playlist_id,
                    provider_domain=self.domain,
                    provider_instance=self.instance_id,
                )
            },
        )

    async def get_playlist_tracks(self, prov_playlist_id: str, page: int = 0) -> list[Track]:
        items = await asyncio.to_thread(
            lambda: list(self._client.get_tracks(prov_playlist_id))
        )
        return [_to_track(i, self.domain, self.instance_id) for i in items]

    async def get_track(self, prov_track_id: str) -> Track:
        # Return a stub — stream details are resolved lazily in get_stream_details.
        # The track URL is the item_id so MA can pass it back for stream resolution.
        slug = prov_track_id.rstrip("/").split("/")[-1].replace("-", " ").title()
        return Track(
            item_id=prov_track_id,
            provider=self.domain,
            name=slug,
            provider_mappings={
                ProviderMapping(
                    item_id=prov_track_id,
                    provider_domain=self.domain,
                    provider_instance=self.instance_id,
                    audio_format=AudioFormat(content_type=ContentType.AAC),
                )
            },
        )

    async def get_stream_details(self, item_id: str, media_type: MediaType) -> StreamDetails:
        stream_url = await asyncio.to_thread(self._client.resolve_stream, item_id)
        if not stream_url:
            raise MediaNotFoundError(f"No stream available for: {item_id}")
        is_hls = "m3u8" in stream_url
        return StreamDetails(
            provider=self.domain,
            item_id=item_id,
            audio_format=AudioFormat(content_type=ContentType.AAC),
            media_type=MediaType.TRACK,
            stream_type=StreamType.HLS if is_hls else StreamType.HTTP,
            path=stream_url,
            can_seek=True,
            allow_seek=True,
        )
