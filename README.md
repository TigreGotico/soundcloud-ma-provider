# soundcloud-ma-provider

[Music Assistant](https://music-assistant.io) provider for [SoundCloud](https://soundcloud.com) — search and stream tracks, browse artist profiles and playlists/sets, without a SoundCloud account, via [`nuvem_de_som`](https://github.com/TigreGotico/nuvem_de_som).

| Provider domain | Content |
|---|---|
| `soundcloud_free` | Tracks, artists, playlists/sets |

Stream URLs are resolved at play-time from SoundCloud's public stream endpoint. No credentials, no client ID registration, no OAuth.

---

## Table of contents

- [Quick start](#quick-start)
- [What you get](#what-you-get)
- [How it works](#how-it-works)
- [Provider reference](#provider-reference)
- [Architecture deep-dive](#architecture-deep-dive)
- [Development guide](#development-guide)
- [Troubleshooting](#troubleshooting)

---

## Quick start

### 1. Install

```bash
pip install soundcloud-ma-provider
```

Dependencies pulled in automatically:

| Package | Role |
|---|---|
| `music-assistant-plugin-manager` | Registers the provider with MA at startup |
| `nuvem_de_som` | SoundCloud search, user/playlist resolution, stream URL extraction |

### 2. Launch Music Assistant through the plugin manager

```bash
mass-pm
```

### 3. Enable the provider

In Music Assistant: **Settings → Providers → SoundCloud (no login) → +**

No configuration fields — click + and you're done.

---

## What you get

**Search**: tracks, artists (SoundCloud "people"), and playlists/sets by keyword.

**Artist profiles**: navigate to an artist from any search result. The artist profile shows their uploaded tracks.

**Playlists / Sets**: browse and play any public SoundCloud set.

**Browse**: a "Trending" shortcut surfaces popular tracks from SoundCloud's public trending feed.

**What is not available**: private tracks, tracks behind a SoundCloud Go+ paywall. Only publicly streamable tracks play. The stream format is AAC — delivered as HLS or plain HTTP depending on the track and SoundCloud's CDN routing.

---

## How it works

```
User searches "Burial"
         │
         └─ SoundCloudProvider.search()
                ├─ client.search_tracks("Burial", limit=10)    ← nuvem_de_som
                ├─ client.search_people("Burial", limit=10)
                └─ client.search_sets("Burial", limit=10)

User follows artist "Burial"
         │
         └─ get_artist_toptracks("https://soundcloud.com/burial")
                └─ client.get_tracks("https://soundcloud.com/burial")
                         └─ list of track dicts → Track objects

User presses Play
         │
         └─ get_stream_details("https://soundcloud.com/burial/archangel")
                └─ client.resolve_stream("https://soundcloud.com/burial/archangel")
                         └─ SoundCloud stream URL (HLS .m3u8 or plain HTTP)
                              └─ StreamDetails(HLS or HTTP, AAC)
                                   └─ MA fetches and plays
```

The stream type is detected automatically: if the resolved URL contains `m3u8`, `StreamType.HLS` is used; otherwise `StreamType.HTTP`. MA handles both.

---

## Provider reference

**Source**: `soundcloud_ma_provider/__init__.py`  
**Domain**: `soundcloud_free`  
**Audio format**: AAC (stream type: HLS or HTTP, detected at resolution time)

### Supported features

| Feature | Description |
|---|---|
| `SEARCH` | Tracks, artists, playlists/sets |
| `ARTIST_TOPTRACKS` | Artist's uploaded tracks |
| `BROWSE` | Trending tracks shortcut |

### Media type mapping

| MA type | SoundCloud concept | item\_id format |
|---|---|---|
| `Track` | Track | `https://soundcloud.com/<user>/<track-slug>` |
| `Artist` | User / profile | `https://soundcloud.com/<user>` |
| `Playlist` | Set / playlist | `https://soundcloud.com/<user>/sets/<set-slug>` |

Item IDs are always full SoundCloud page URLs. `nuvem_de_som` accepts these directly in all resolution calls — no ID-to-URL conversion is needed.

### Methods

| Method | What it does |
|---|---|
| `search(query, media_types, limit)` | Searches SoundCloud for tracks, people, and/or sets |
| `get_artist(prov_artist_id)` | Resolves user profile by URL; falls back to a name stub on failure |
| `get_artist_toptracks(prov_artist_id)` | Returns the artist's uploaded tracks |
| `get_playlist(prov_playlist_id)` | Returns a minimal playlist stub (title derived from URL slug) |
| `get_playlist_tracks(prov_playlist_id, page)` | Fetches set track listing via `client.get_tracks()` |
| `get_track(prov_track_id)` | Returns a stub track (metadata resolved lazily at stream time) |
| `browse(path)` | Returns a "Trending" folder at root; trending tracks one level deep |
| `get_stream_details(item_id, media_type)` | Resolves SoundCloud page URL to audio stream |

### `get_playlist()` stub behaviour

`get_playlist()` returns a minimal `Playlist` object with the title derived from the URL slug (`sets/my-cool-mix` → `"My Cool Mix"`) rather than fetching the set page. This avoids an extra HTTP round-trip for the common case where MA only needs the playlist title for display. The full track listing is fetched in `get_playlist_tracks()`.

### `get_track()` stub behaviour

`get_track()` similarly returns a stub `Track` with the title derived from the URL slug. The real metadata (title, artwork, duration) would require an additional page fetch that is not worth the latency — MA calls `get_stream_details()` immediately after and the player does not need rich metadata to start playback.

### Stream type detection

```python
is_hls = "m3u8" in stream_url
StreamDetails(
    stream_type=StreamType.HLS if is_hls else StreamType.HTTP,
    ...
)
```

SoundCloud serves some tracks as plain HTTP AAC and others as HLS (`.m3u8`) playlists — the choice depends on the track's upload format and SoundCloud's CDN routing. MA's player handles both.

### Artist resolution fallback

`get_artist()` calls `client.resolve_user(url)`. If the resolution fails (network error, unknown user), a stub `Artist` is returned with the name derived from the URL slug rather than raising. This makes stale library entries show a name rather than breaking.

---

## Architecture deep-dive

### Discovery

```toml
[project.entry-points."music_assistant.provider"]
soundcloud_free = "soundcloud_ma_provider"
```

`mass-pm` reads this entrypoint at startup via `music-assistant-plugin-manager` and injects the `soundcloud_free` domain into MA's provider registry before MA's own startup code runs. See [plugin-managers](https://github.com/TigreGotico/plugin-managers) for the full mechanism.

### `nuvem_de_som` client lifecycle

```python
async def handle_async_init(self) -> None:
    from nuvem_de_som import SoundCloudAPI
    self._client = SoundCloudAPI()
```

`SoundCloudAPI()` is instantiated once per provider instance and holds internal state across calls (e.g. the SoundCloud client ID extracted from the page). The import is deferred to `handle_async_init()` so a missing dependency raises `ProviderUnavailableError` cleanly rather than crashing at module import time.

### All network calls run in a thread

Every `nuvem_de_som` call is synchronous. All are wrapped in `asyncio.to_thread` to avoid blocking the MA event loop:

```python
items = await asyncio.to_thread(
    lambda: list(self._client.search_tracks(search_query, limit=limit))
)
```

### Data shape from `nuvem_de_som`

`nuvem_de_som` returns plain Python dicts. The conversion helpers (`_to_track`, `_to_artist`, `_to_playlist`) extract fields by key with safe defaults:

```python
def _to_track(item: dict, domain: str, instance_id: str) -> Track:
    page_url = item.get("url", "")
    artist_name = item.get("artist") or "Unknown"
    artist_url = item.get("artist_url") or ""
    ...
```

When `artist_url` is present it is used as the artist's `item_id`, so clicking an artist from a track result navigates correctly to their profile page.

---

## Development guide

### Set up

```bash
git clone https://github.com/TigreGotico/soundcloud-ma-provider
cd soundcloud-ma-provider
pip install -e .
```

Also install `nuvem_de_som` from source if needed:

```bash
git clone https://github.com/TigreGotico/nuvem_de_som
pip install -e ../nuvem_de_som
```

### Explore the `nuvem_de_som` API

```python
from nuvem_de_som import SoundCloudAPI

sc = SoundCloudAPI()

# Search
for t in sc.search_tracks("burial", limit=5):
    print(t["title"], t["url"], t["duration"])

for u in sc.search_people("burial", limit=5):
    print(u["artist"], u["artist_url"])

for s in sc.search_sets("burial", limit=5):
    print(s["title"], s["url"])

# Artist profile
user = sc.resolve_user("https://soundcloud.com/burial-official")
print(user)

# Artist tracks
for t in sc.get_tracks("https://soundcloud.com/burial-official"):
    print(t["title"], t["url"])

# Set tracks
for t in sc.get_tracks("https://soundcloud.com/burial-official/sets/untrue"):
    print(t["title"])

# Stream URL
url = sc.resolve_stream("https://soundcloud.com/burial-official/archangel")
print(url)   # direct stream URL (HTTP or HLS .m3u8)
```

### Adding rich playlist metadata

Currently `get_playlist()` derives the title from the URL slug. To fetch the real title and artwork, add a `resolve_set()` call if `nuvem_de_som` exposes one:

```python
async def get_playlist(self, prov_playlist_id: str) -> Playlist:
    data = await asyncio.to_thread(self._client.resolve_set, prov_playlist_id)
    if data:
        return _to_playlist(data, self.domain, self.instance_id)
    # fallback
    slug = prov_playlist_id.rstrip("/").split("/")[-1].replace("-", " ").title()
    return Playlist(item_id=prov_playlist_id, provider=self.domain, name=slug, ...)
```

If `nuvem_de_som` does not have `resolve_set`, open a feature request on that repo.

### Adding more browse content

The browse method currently surfaces one "Trending" folder. To add genre folders:

```python
GENRES = ["electronic", "hip-hop", "ambient", "jazz"]

async def browse(self, path):
    parts = ...
    if not parts:
        return [BrowseFolder(..., name=g.title()) for g in GENRES]
    genre = parts[0]
    items = await asyncio.to_thread(
        lambda: list(self._client.search_tracks(f"{genre}", limit=20))
    )
    return [_to_track(i, self.domain, self.instance_id) for i in items]
```

Also add `ProviderFeature.BROWSE` to `SUPPORTED_FEATURES`.

---

## Troubleshooting

### "No stream available" error

`get_stream_details` raises `MediaNotFoundError` when `client.resolve_stream()` returns `None`. Possible causes:

- Track is private or behind SoundCloud Go+.
- SoundCloud updated its stream endpoint and `nuvem_de_som` needs updating.
- Regional restriction.

Update first:

```bash
pip install -U nuvem_de_som
```

### Search returns no results

`nuvem_de_som` extracts SoundCloud's client ID from the page at startup. If SoundCloud updates its page structure and extraction fails, all search calls return nothing. Update `nuvem_de_som` and, if the problem persists, open an issue on its repository.

### Artist tracks list is empty

`get_tracks(artist_url)` scrapes the artist's profile page. If the artist has no public uploads, or SoundCloud's layout changed, this returns empty. Check for `nuvem_de_som` updates.

### HLS playback is choppy or fails

Some MA audio backends have partial HLS support. MPV generally handles HLS well; simpler backends may not. If you see problems, check your MA audio backend configuration.

### Provider not appearing in MA

```bash
python -c "
from music_assistant_plugin_manager import find_providers
print(find_providers())
"
# expected: {"soundcloud_free": "soundcloud_ma_provider", ...}
```

If missing: verify `pip install soundcloud-ma-provider` succeeded and that you are running `mass-pm`, not `music-assistant` directly.
