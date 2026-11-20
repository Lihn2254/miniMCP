import json, os, signal, subprocess
from typing import Literal

from mcp.server.mcpserver import MCPServer
import threading
from datetime import datetime


from helpers import _load_albums, _save_album, _write_albums, run_soloist_ctl_command
from helpers import start_soloist as _start_soloist
from schemas import Album, Track

SERVER_INSTRUCTIONS = """\
This server manages a local library of albums and tracks and controls playback through Soloist, a Spotify CLI player.

## Library
- Albums and tracks are identified by their Spotify URI ('spotify:album:...' and 'spotify:track:...').
- When asked to register an album or track without a URI or name, ask the user for them. Never invent a URI or name.
- Tracks belong to an album: to register a track, first find the album and use its URI.

## Playback
- Soloist must be running for any playback command. If a tool reports that it is not running, start it with the matching tool and retry.
- Soloist must be the active playback session for audio to play. Activate it after starting it, or when the status shows it is not the active device.
- To play an album or track, first look up its URI in the library and pass it to the playback tool. If it is not in the library, tell the user instead of guessing the URI.
- Playing without a URI resumes the current playback. Pause, next, previous and seek (position in milliseconds) do not need a URI.
- Volume is an integer between 0 and 100.
- Shuffle is turned on or off. Repeat mode is 'off', 'context' (repeats the current album or playlist) or 'track' (repeats the current track).
- Use the now-playing tool to see what is playing, and the queue tool to see upcoming tracks (10 by default; the user may ask for any positive number).
- If something fails and the reason is unclear, check the Soloist status (session, login and active device).
"""

mcp = MCPServer("MCPlayer_Server", instructions=SERVER_INSTRUCTIONS)


_lock = threading.Lock()
_soloist_proc: subprocess.Popen | None = None


def _terminate_soloist(proc: subprocess.Popen) -> None:
    """Ask the Soloist process to exit, killing it if it does not stop in time."""
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _shutdown_soloist() -> None:
    """Stop the Soloist process, if any, when the server shuts down."""
    global _soloist_proc

    # Don't hang forever if a tool call is still holding the lock
    acquired = _lock.acquire(timeout=5)
    try:
        proc, _soloist_proc = _soloist_proc, None
        if proc is not None and proc.poll() is None:
            _terminate_soloist(proc)
    finally:
        if acquired:
            _lock.release()


def _run_ctl_if_running(args: list[str]) -> tuple[bool, str]:
    """Run a soloist ctl command while holding the lock.

    Returns `(ok, output)`. When `ok` is False, `output` is a ready-to-return
    error message; otherwise it is the command's output.
    """
    global _soloist_proc

    with _lock:
        if _soloist_proc is None or _soloist_proc.poll() is not None:
            _soloist_proc = None
            return False, "Soloist is not running."

        return_code, output = run_soloist_ctl_command(args)

    if return_code != 0:
        return False, f"Command failed with exit code {return_code}. Output: {output}"
    return True, output


TRACK_URI_PREFIX = "spotify:track:"


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
def register_track(track: Track, album_uri: str) -> str:
    if not track.uri.startswith(TRACK_URI_PREFIX):
        return f"Error: Track URI must start with '{TRACK_URI_PREFIX}'."

    with _lock:
        albums = _load_albums()
        album = _find_album(albums, album_uri)
        if album is None:
            return f"Error: Album '{album_uri}' does not exist."

        if any(t.uri.lower() == track.uri.lower() for t in album.tracks):
            return f"Error: Track '{track.uri}' already exists in album '{album.name}'."

        album.tracks.append(track)
        _write_albums(albums)
    return f"Track '{track.name}' added to album '{album.name}'."


@mcp.tool(
    description="Search tracks across all albums by a partial, case-insensitive name match. Returns every match along with its album."
)
def get_track_by_name(name: str) -> str:
    with _lock:
        albums = _load_albums()
    return _find_tracks(albums, lambda t: name.lower() in t.name.lower())


@mcp.tool(
    description="Search tracks across all albums by exact URI. Returns every match along with its album."
)
def get_track_by_uri(uri: str) -> str:
    with _lock:
        albums = _load_albums()
    return _find_tracks(albums, lambda t: t.uri.lower() == uri.lower())


@mcp.tool(
    description="Update the name and/or URI of a track inside an album. Provide at least one of new_name or new_uri."
)
def update_track(
    album_uri: str,
    track_uri: str,
    new_name: str | None = None,
    new_uri: str | None = None,
) -> str:
    if new_name is None and new_uri is None:
        return "Error: Provide at least one of 'new_name' or 'new_uri'."
    if new_uri is not None and not new_uri.startswith(TRACK_URI_PREFIX):
        return f"Error: Track URI must start with '{TRACK_URI_PREFIX}'."

    with _lock:
        albums = _load_albums()
        album = _find_album(albums, album_uri)
        if album is None:
            return f"Error: Album '{album_uri}' does not exist."

        track = next(
            (t for t in album.tracks if t.uri.lower() == track_uri.lower()), None
        )
        if track is None:
            return f"Error: Track '{track_uri}' does not exist in album '{album.name}'."

        if new_uri is not None and any(
            t is not track and t.uri.lower() == new_uri.lower() for t in album.tracks
        ):
            return f"Error: Track '{new_uri}' already exists in album '{album.name}'."

        if new_name is not None:
            track.name = new_name
        if new_uri is not None:
            track.uri = new_uri
        _write_albums(albums)
    return f"Track updated:\n{track.model_dump_json()}"


@mcp.tool(description="Remove a track from an album")
def delete_track(album_uri: str, track_uri: str) -> str:
    with _lock:
        albums = _load_albums()
        album = _find_album(albums, album_uri)
        if album is None:
            return f"Error: Album '{album_uri}' does not exist."

        remaining = [t for t in album.tracks if t.uri.lower() != track_uri.lower()]
        if len(remaining) == len(album.tracks):
            return f"Error: Track '{track_uri}' does not exist in album '{album.name}'."

        album.tracks = remaining
        _write_albums(albums)
    return f"Track '{track_uri}' removed from album '{album.name}'."


@mcp.tool(
    description="Update the name and/or artist of an album, identified by its URI. Provide at least one of new_name or new_artist."
)
def update_album(
    uri: str, new_name: str | None = None, new_artist: str | None = None
) -> str:
    if new_name is None and new_artist is None:
        return "Error: Provide at least one of 'new_name' or 'new_artist'."

    with _lock:
        albums = _load_albums()
        album = _find_album(albums, uri)
        if album is None:
            return f"Error: Album '{uri}' does not exist."

        if new_name is not None:
            if any(a is not album and a.name == new_name for a in albums):
                return f"Error: An album named '{new_name}' already exists."
            album.name = new_name
        if new_artist is not None:
            album.artist = new_artist
        _write_albums(albums)
    return f"Album updated:\n{album.model_dump_json(exclude={'tracks'})}"


@mcp.tool(description="Delete an album, and all of its tracks, by its URI")
def delete_album(uri: str) -> str:
    with _lock:
        albums = _load_albums()
        album = _find_album(albums, uri)
        if album is None:
            return f"Error: Album '{uri}' does not exist."

        _write_albums([a for a in albums if a is not album])
    return f"Album '{album.name}' deleted."
    

@mcp.tool(description="Create and store a new album")
def register_album(album: Album) -> str:
    with _lock:
        albums = _load_albums()
        for a in albums:
            if album.name == a.name:
                return f"Error: An album named '{album.name}' already exists."
        _save_album(album)
    return f"Album '{album.name}' created successfully."


@mcp.tool(description="Find and read an album by a partial match on its name")
def get_album_by_name(name: str, include_tracks: bool = True) -> str:
    albums = _load_albums()
    print(albums)
    for a in albums:
        if name.lower() in a.name.lower():
            if include_tracks:
                return f"Album found:\n{a.model_dump_json()}"
            else:
                return f"Album found:\n{a.model_dump_json(exclude={"tracks"})}"

    return "The album could not be found."


@mcp.tool(description="Find and read an album by an exact match on its URI")
def get_album_by_uri(uri: str, include_tracks: bool = True) -> str:
    albums = _load_albums()
    for a in albums:
        if uri.lower() == a.uri.lower():
            if include_tracks:
                return f"Album found:\n{a.model_dump_json()}"
            else:
                return f"Album found:\n{a.model_dump_json(exclude={"tracks"})}"

    return "The album could not be found."


@mcp.tool(
    description="Start the Soloist (Spotify CLI player) process in the background"
)
def start_soloist() -> str:
    global _soloist_proc

    with _lock:
        if _soloist_proc is not None and _soloist_proc.poll() is None:
            return f"Soloist is already running (pid {_soloist_proc.pid})."

        proc, message = _start_soloist()
        if proc is not None:
            _soloist_proc = proc
        return message


@mcp.tool(description="Stop the Soloist process started by start_soloist")
def stop_soloist() -> str:
    global _soloist_proc

    with _lock:
        if _soloist_proc is None or _soloist_proc.poll() is not None:
            _soloist_proc = None
            return "Soloist is not running."
        _terminate_soloist(_soloist_proc)
        _soloist_proc = None
        return "Soloist stopped."


@mcp.tool(
    description="Set Soloist as the active playback session. Requires Soloist to be running."
)
def activate_soloist() -> str:
    ok, output = _run_ctl_if_running(["activate"])
    if not ok:
        return output
    return "Successfully set Soloist as the active playback session"


# @mcp.tool(
#     description="Play an album by its Spotify URI"
# )
# def play(uri: str | None) -> str:
#     if uri and not uri.startswith("spotify:"):
#         return f"Error: The provided URI has an invalid format."

#     global _soloist_proc

#     with _lock:
#         if _soloist_proc is None or _soloist_proc.poll() is not None:
#             _soloist_proc = None
#             return "Soloist is not running."

#         args = ["play", uri]
#         return_code, output = run_soloist_ctl_command(args)

#         if return_code == -1:
#             return f"Command failed with exit code {return_code}. Output: {output}"
#         else:
#             return f"Started album playback successfully."


@mcp.tool(description="""
        Controls the playback state of Soloist. 
        To start playback a valid URI must be provided.
        All other actions do not require a URI.
        """)
def manage_playback(
    action: Literal["play", "pause", "next", "prev", "seek"],
    uri: str | None = None,
    ms: int | None = None,
):
    args = [action]

    if action == "play" and uri:
        if not uri.startswith("spotify:"):
            return f"Error: Provided URI has an invalid format."

        args.append(uri)

    if action == "seek":
        if not ms:
            return f"Error: When using 'seek' command miliseconds must be provided."

        args.append(str(ms))

    ok, output = _run_ctl_if_running(args)
    if not ok:
        return output
    return f"{action} command executed succesfully."


@mcp.tool(
    description="Set playback volume. Must be a value between 0 and 100 (inclusive)"
)
def set_volume(value: int) -> str:
    if not (value <= 100 and value >= 0):
        return f"Error: Invalid value for volume."

    ok, output = _run_ctl_if_running(["volume", str(value)])
    if not ok:
        return output
    return f"Volume set to {value}"


@mcp.tool(
    description="Show daemon status, WebSocket availability, login state, and active-device state. Does not require login."
)
def get_status() -> str:
    _, output = _run_ctl_if_running(["status"])
    return output


@mcp.tool(description="Turn shuffle on or off for the current playback")
def set_shuffle(enabled: bool) -> str:
    ok, output = _run_ctl_if_running(["shuffle", "on" if enabled else "off"])
    if not ok:
        return output
    return f"Shuffle turned {'on' if enabled else 'off'}."


@mcp.tool(
    description="""
        Set the repeat mode.
        'off' disables repeat, 'context' repeats the current album/playlist,
        'track' repeats the current track.
        """
)
def set_repeat(mode: Literal["off", "context", "track"]) -> str:
    ok, output = _run_ctl_if_running(["repeat", mode])
    if not ok:
        return output
    return f"Repeat mode set to '{mode}'."


@mcp.tool(description="Show the current playback state (now playing track, progress, etc.)")
def get_now_playing() -> str:
    _, output = _run_ctl_if_running(["now"])
    return output


@mcp.tool(
    description="Show the upcoming tracks in the queue. 'limit' must be a positive integer (default 10)."
)
def get_queue(limit: int = 10) -> str:
    if limit <= 0:
        return "Error: 'limit' must be a positive number."

    _, output = _run_ctl_if_running(["queue", str(limit)])
    return output


@mcp.tool()
def get_local_datetime() -> str:
    """Get the current datetime in the server's timezone"""
    return datetime.now().isoformat()


if __name__ == "__main__":
    SERVER_TRANSPORT = os.environ.get(key="SERVER_TRANSPORT", default="http")
    SERVER_HOST = os.environ.get(key="SERVER_HOST", default="127.0.0.1")
    SERVER_PORT = int(os.environ.get(key="SERVER_PORT", default="8000"))

    if SERVER_TRANSPORT not in ["http", "stdio"]:
        raise Exception('SERVER_TRANSPORT must be "http" or "stdio"')

    # Turn termination signals into a normal interpreter exit so the `finally`
    # below runs (Ctrl+C already raises KeyboardInterrupt). SIGBREAK only
    # exists on Windows, where its default action kills the process outright.
    def _exit_on_signal(_signum, _frame):
        raise SystemExit(0)

    for _sig in (signal.SIGTERM, getattr(signal, "SIGBREAK", None)):
        if _sig is not None:
            signal.signal(_sig, _exit_on_signal)

    try:
        if SERVER_TRANSPORT == "http":
            mcp.run(transport="streamable-http", host=SERVER_HOST, port=SERVER_PORT)
        else:
            mcp.run()
    finally:
        _shutdown_soloist()
