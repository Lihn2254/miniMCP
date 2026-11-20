import json, os, sys
from typing import Annotated, Literal

import psutil
from pydantic import Field
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
import threading
from datetime import datetime

from helpers import _load_albums, _write_albums, run_soloist_ctl_command
from helpers import start_soloist as _start_soloist
from schemas import Album, AlbumUri, NonEmptyStr, Track, TrackUri
from config import get_settings

SERVER_INSTRUCTIONS = """\
This server manages a local library of albums and tracks and controls playback through Soloist, a Spotify CLI player.

## Library
- Albums and tracks are identified by their Spotify URI ('spotify:album:...' and 'spotify:track:...').
- When asked to register an album or track without a URI or name, ask the user for them. Never invent a URI or name.
- When asked to register an album or track use the available tools and ask user for the required parameters if needed. Never invent albums or tracks.
- Tracks belong to an album: to register a track, first find the album and use its URI.

## Playback
- Soloist must be running for any playback command. If a tool reports that it is not running, start it with the matching tool and retry.
- Soloist must be the active playback session for audio to play. Activate it after starting it, or when the status shows it is not the active device.
- To play an album or track, first look up its URI in the library and pass it to the playback tool. If it is not in the library, tell the user instead of guessing the URI.
- Playing without a URI resumes the current playback. Pause, next, previous and seek (position in milliseconds) do not need a URI.
- Volume is an integer between 0 and 100.
- Shuffle is turned on or off. Repeat mode is 'off', 'context' (repeats the current album or playlist) or 'track' (repeats the current track).
- Use the now-playing tool to see what is playing, and the queue tool to see upcoming tracks (10 by default; the user may ask for any number from 1 to 50).
- If something fails and the reason is unclear, check the Soloist status (session, login and active device).
"""

mcp = MCPServer("MCPlayer_Server", instructions=SERVER_INSTRUCTIONS)


_lock = threading.Lock()
# The Soloist daemon, whether this server started it or found it already
# running. It is deliberately NOT stopped when the server exits, so playback
# survives a server restart.
_soloist_proc: psutil.Process | None = None

SOLOIST_PROCESS_NAME = "soloist"


def _is_alive(proc: psutil.Process | None) -> bool:
    """True if `proc` is still running (a zombie counts as not running)."""
    if proc is None:
        return False
    try:
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _is_soloist_daemon(name: str | None, cmdline: list[str]) -> bool:
    """True if a process with this name and command line is the Soloist daemon.

    `soloist ctl ...` invocations also run a process called soloist, but they
    are short-lived clients and must not be mistaken for the daemon.
    """
    if os.path.splitext((name or "").lower())[0] != SOLOIST_PROCESS_NAME:
        return False
    return not (len(cmdline) > 1 and cmdline[1] == "ctl")


def _find_running_soloist() -> psutil.Process | None:
    """Look through the system's processes for an already running Soloist
    daemon. If there are several, the oldest one is returned."""
    candidates = [
        p
        for p in psutil.process_iter(["name", "cmdline", "create_time"])
        if _is_soloist_daemon(p.info["name"], p.info["cmdline"] or [])
        and _is_alive(p)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda p: p.info["create_time"] or 0)


def _terminate_soloist(proc: psutil.Process) -> None:
    """Ask the Soloist process to exit, killing it if it does not stop in time."""
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except psutil.TimeoutExpired:
            proc.kill()
            proc.wait()
    except psutil.NoSuchProcess:
        pass  # it exited on its own in the meantime


def _run_ctl_if_running(args: list[str]) -> str:
    """Run a soloist ctl command while holding the lock.

    Returns the command's output. Raises `ToolError` (reported to the client as
    an MCP `isError` result) if Soloist is not running or the command fails.
    """
    global _soloist_proc

    with _lock:
        if not _is_alive(_soloist_proc):
            _soloist_proc = None
            raise ToolError("Soloist is not running.")

        return_code, output = run_soloist_ctl_command(args)

    if return_code != 0:
        raise ToolError(f"Command failed with exit code {return_code}. Output: {output}")
    return output


MAX_QUEUE_LIMIT = 50

# Reusable parameter types with descriptions, so the generated tool schemas are
# self-explanatory for the LLM.
AlbumUriParam = Annotated[
    AlbumUri, Field(description="Spotify URI of the album, e.g. 'spotify:album:<id>'")
]
TrackUriParam = Annotated[
    TrackUri, Field(description="Spotify URI of the track, e.g. 'spotify:track:<id>'")
]
SpotifyUriParam = Annotated[
    str,
    Field(
        description="Any Spotify URI (track, album, playlist...), starting with 'spotify:'"
    ),
]


def _find_album(albums: list[Album], uri: str) -> Album | None:
    """Return the album whose URI matches `uri` exactly (case-insensitive)."""
    for a in albums:
        if a.uri.lower() == uri.lower():
            return a
    return None


def _find_tracks(albums: list[Album], matches) -> str:
    """Serialize every track for which `matches(track)` is true, together with
    the album that contains it."""
    results = [
        {"album": {"name": a.name, "uri": a.uri}, "track": t.model_dump()}
        for a in albums
        for t in a.tracks
        if matches(t)
    ]
    if not results:
        return "The track could not be found."
    return f"Found {len(results)} track(s):\n" + json.dumps(
        results, ensure_ascii=False
    )


@mcp.tool(
    description="Add a track to an existing album, identified by the album's URI"
)
def register_track(
    track: Track,
    album_uri: Annotated[
        AlbumUri, Field(description="URI of the existing album the track is added to")
    ],
) -> str:
    with _lock:
        albums = _load_albums()
        album = _find_album(albums, album_uri)
        if album is None:
            raise ToolError(f"Album '{album_uri}' does not exist.")

        if any(t.uri.lower() == track.uri.lower() for t in album.tracks):
            raise ToolError(f"Track '{track.uri}' already exists in album '{album.name}'.")

        album.tracks.append(track)
        _write_albums(albums)
    return f"Track '{track.name}' added to album '{album.name}'."


@mcp.tool(
    description="Search tracks across all albums by a partial, case-insensitive name match. Returns every match along with its album."
)
def get_track_by_name(
    name: Annotated[
        NonEmptyStr, Field(description="Full or partial track name to search for")
    ],
) -> str:
    with _lock:
        albums = _load_albums()
    return _find_tracks(albums, lambda t: name.lower() in t.name.lower())


@mcp.tool(
    description="Search tracks across all albums by exact URI. Returns every match along with its album."
)
def get_track_by_uri(uri: TrackUriParam) -> str:
    with _lock:
        albums = _load_albums()
    return _find_tracks(albums, lambda t: t.uri.lower() == uri.lower())


@mcp.tool(
    description="Update the name and/or URI of a track inside an album. Provide at least one of new_name or new_uri."
)
def update_track(
    album_uri: Annotated[
        AlbumUri, Field(description="URI of the album that contains the track")
    ],
    track_uri: Annotated[
        TrackUri, Field(description="Current URI of the track to update")
    ],
    new_name: Annotated[
        NonEmptyStr | None, Field(description="New name for the track")
    ] = None,
    new_uri: Annotated[
        TrackUri | None, Field(description="New Spotify URI for the track")
    ] = None,
) -> str:
    if new_name is None and new_uri is None:
        raise ToolError("Provide at least one of 'new_name' or 'new_uri'.")

    with _lock:
        albums = _load_albums()
        album = _find_album(albums, album_uri)
        if album is None:
            raise ToolError(f"Album '{album_uri}' does not exist.")

        track = next(
            (t for t in album.tracks if t.uri.lower() == track_uri.lower()), None
        )
        if track is None:
            raise ToolError(f"Track '{track_uri}' does not exist in album '{album.name}'.")

        if new_uri is not None and any(
            t is not track and t.uri.lower() == new_uri.lower() for t in album.tracks
        ):
            raise ToolError(f"Track '{new_uri}' already exists in album '{album.name}'.")

        if new_name is not None:
            track.name = new_name
        if new_uri is not None:
            track.uri = new_uri
        _write_albums(albums)
    return f"Track updated:\n{track.model_dump_json()}"


@mcp.tool(description="Remove a track from an album")
def delete_track(
    album_uri: Annotated[
        AlbumUri, Field(description="URI of the album that contains the track")
    ],
    track_uri: Annotated[TrackUri, Field(description="URI of the track to remove")],
) -> str:
    with _lock:
        albums = _load_albums()
        album = _find_album(albums, album_uri)
        if album is None:
            raise ToolError(f"Album '{album_uri}' does not exist.")

        remaining = [t for t in album.tracks if t.uri.lower() != track_uri.lower()]
        if len(remaining) == len(album.tracks):
            raise ToolError(f"Track '{track_uri}' does not exist in album '{album.name}'.")

        album.tracks = remaining
        _write_albums(albums)
    return f"Track '{track_uri}' removed from album '{album.name}'."


@mcp.tool(
    description="Update the name and/or artist of an album, identified by its URI. Provide at least one of new_name or new_artist."
)
def update_album(
    uri: Annotated[AlbumUri, Field(description="URI of the album to update")],
    new_name: Annotated[
        NonEmptyStr | None, Field(description="New name for the album")
    ] = None,
    new_artist: Annotated[
        NonEmptyStr | None, Field(description="New artist for the album")
    ] = None,
) -> str:
    if new_name is None and new_artist is None:
        raise ToolError("Provide at least one of 'new_name' or 'new_artist'.")

    with _lock:
        albums = _load_albums()
        album = _find_album(albums, uri)
        if album is None:
            raise ToolError(f"Album '{uri}' does not exist.")

        if new_name is not None:
            if any(a is not album and a.name == new_name for a in albums):
                raise ToolError(f"An album named '{new_name}' already exists.")
            album.name = new_name
        if new_artist is not None:
            album.artist = new_artist
        _write_albums(albums)
    return f"Album updated:\n{album.model_dump_json(exclude={'tracks'})}"


@mcp.tool(description="Delete an album, and all of its tracks, by its URI")
def delete_album(
    uri: Annotated[AlbumUri, Field(description="URI of the album to delete")],
) -> str:
    with _lock:
        albums = _load_albums()
        album = _find_album(albums, uri)
        if album is None:
            raise ToolError(f"Album '{uri}' does not exist.")

        _write_albums([a for a in albums if a is not album])
    return f"Album '{album.name}' deleted."
    

@mcp.tool(description="Create and store a new album")
def register_album(album: Album) -> str:
    with _lock:
        albums = _load_albums()
        if _find_album(albums, album.uri) is not None:
            raise ToolError(f"An album with URI '{album.uri}' already exists.")
        if any(album.name.lower() == a.name.lower() for a in albums):
            raise ToolError(f"An album named '{album.name}' already exists.")
        albums.append(album)
        _write_albums(albums)
    return f"Album '{album.name}' created successfully."


@mcp.tool(description="Find and read an album by a partial match on its name")
def get_album_by_name(
    name: Annotated[
        NonEmptyStr, Field(description="Full or partial album name to search for")
    ],
    include_tracks: Annotated[
        bool, Field(description="Whether to include the album's tracks in the result")
    ] = True,
) -> str:
    albums = _load_albums()
    for a in albums:
        if name.lower() in a.name.lower():
            if include_tracks:
                return f"Album found:\n{a.model_dump_json()}"
            else:
                return f"Album found:\n{a.model_dump_json(exclude={"tracks"})}"

    return "The album could not be found."


@mcp.tool(description="Find and read an album by an exact match on its URI")
def get_album_by_uri(
    uri: AlbumUriParam,
    include_tracks: Annotated[
        bool, Field(description="Whether to include the album's tracks in the result")
    ] = True,
) -> str:
    albums = _load_albums()
    for a in albums:
        if uri.lower() == a.uri.lower():
            if include_tracks:
                return f"Album found:\n{a.model_dump_json()}"
            else:
                return f"Album found:\n{a.model_dump_json(exclude={"tracks"})}"

    return "The album could not be found."

@mcp.tool(description="Retrieve all registered albums")
def get_all_albums(
    include_tracks: Annotated[
        bool, Field(description="Whether to include each album's tracks in the result")
    ] = False,
) -> str:
    albums = _load_albums()

    if len(albums) <= 0:
        return f"There are no registered albums."

    return "\n".join(
        album.model_dump_json(exclude={"tracks"} if not include_tracks else None)
        for album in albums
    )


@mcp.tool(
    description="Start the Soloist (Spotify CLI player) process in the background"
)
def start_soloist() -> str:
    global _soloist_proc

    with _lock:
        if _is_alive(_soloist_proc):
            return f"Soloist is already running (pid {_soloist_proc.pid})."

        # It may have been started outside this server (e.g. manually)
        existing = _find_running_soloist()
        if existing is not None:
            _soloist_proc = existing
            return f"Soloist is already running (pid {existing.pid})."

        proc, message = _start_soloist()
        if proc is None:
            raise ToolError(message)
        _soloist_proc = psutil.Process(proc.pid)
        return message


@mcp.tool(description="Stop the Soloist process (the one started by start_soloist, or one that was already running)")
def stop_soloist() -> str:
    global _soloist_proc

    with _lock:
        if not _is_alive(_soloist_proc):
            _soloist_proc = None
            raise ToolError("Soloist is not running.")
        _terminate_soloist(_soloist_proc)
        _soloist_proc = None
        return "Soloist stopped."


@mcp.tool(
    description="Set Soloist as the active playback session. Requires Soloist to be running."
)
def activate_soloist() -> str:
    output = _run_ctl_if_running(["activate"])
    return "Successfully set Soloist as the active playback session"


@mcp.tool(description="""
        Controls the playback state of Soloist. 
        To start playback a valid URI must be provided.
        All other actions do not require a URI.
        """)
def manage_playback(
    action: Annotated[
        Literal["play", "pause", "next", "prev", "seek"],
        Field(description="Playback action to execute"),
    ],
    uri: Annotated[
        str | None,
        Field(
            description="Spotify URI to play (only for 'play'). Omit it to resume the current playback"
        ),
    ] = None,
    ms: Annotated[
        int | None,
        Field(
            ge=0,
            description="Position in milliseconds, 0 or greater (required for 'seek', ignored otherwise)",
        ),
    ] = None,
) -> str:
    args = [action]

    if action == "play" and uri is not None:
        if not uri.startswith("spotify:"):
            raise ToolError("Provided URI has an invalid format.")

        args.append(uri)

    if action == "seek":
        if ms is None:
            raise ToolError("When using 'seek' command milliseconds must be provided.")

        args.append(str(ms))

    output = _run_ctl_if_running(args)
    return f"{action} command executed succesfully."


@mcp.tool(
    description="Set playback volume. Must be a value between 0 and 100 (inclusive)"
)
def set_volume(
    value: Annotated[int, Field(ge=0, le=100, description="Volume level, 0 to 100")],
) -> str:
    output = _run_ctl_if_running(["volume", str(value)])
    return f"Volume set to {value}"


@mcp.tool(
    description="Show daemon status, WebSocket availability, login state, and active-device state. Does not require login."
)
def get_status() -> str:
    output = _run_ctl_if_running(["status"])
    return output


@mcp.tool(description="Turn shuffle on or off for the current playback")
def set_shuffle(
    enabled: Annotated[bool, Field(description="True to turn shuffle on, False to turn it off")],
) -> str:
    output = _run_ctl_if_running(["shuffle", "on" if enabled else "off"])
    return f"Shuffle turned {'on' if enabled else 'off'}."


@mcp.tool(
    description="""
        Set the repeat mode.
        'off' disables repeat, 'context' repeats the current album/playlist,
        'track' repeats the current track.
        """
)
def set_repeat(
    mode: Annotated[
        Literal["off", "context", "track"], Field(description="Repeat mode to apply")
    ],
) -> str:
    output = _run_ctl_if_running(["repeat", mode])
    return f"Repeat mode set to '{mode}'."


@mcp.tool(description="Show the current playback state (now playing track, progress, etc.)")
def get_now_playing() -> str:
    output = _run_ctl_if_running(["now"])
    return output


@mcp.tool(
    description=f"Show the upcoming tracks in the queue. 'limit' must be an integer from 1 to {MAX_QUEUE_LIMIT} (default 10)."
)
def get_queue(
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=MAX_QUEUE_LIMIT,
            description="Maximum number of upcoming tracks to show",
        ),
    ] = 10,
) -> str:
    output = _run_ctl_if_running(["queue", str(limit)])
    return output

@mcp.tool(
    description="Add a track, album or any Spotify resource to the queue by providing its URI"
)
def add_to_queue(uri: SpotifyUriParam) -> str:
    if not uri.startswith("spotify:"):
        raise ToolError("Provided URI has an invalid format.")

    output = _run_ctl_if_running(["add-to-queue", uri])

    return f"{uri} was successfully added to the queue."


@mcp.tool()
def get_local_datetime() -> str:
    """Get the current datetime in the server's timezone"""
    return datetime.now().isoformat()


if __name__ == "__main__":
    settings = get_settings()
    
    # Pick up a Soloist that is already running so it can be controlled (and
    # keeps playing) across server restarts. stderr, because stdout carries
    # the protocol when using the stdio transport.
    _soloist_proc = _find_running_soloist()
    if _soloist_proc is not None:
        print(f"Found running Soloist (pid {_soloist_proc.pid})", file=sys.stderr)

    if settings.SERVER_TRANSPORT == "http":
        print(f"URL: http://{settings.SERVER_HOST}:{settings.SERVER_PORT}{settings.SERVER_PATH}")

        mcp.run(
            transport="streamable-http",
            host=settings.SERVER_HOST,
            port=settings.SERVER_PORT,
            streamable_http_path=settings.SERVER_PATH,
        )
    else:
        mcp.run()
