import os
import subprocess

from mcp.server.mcpserver import MCPServer
import json
import threading
from pathlib import Path
from datetime import datetime

from pydantic import BaseModel, Field, ValidationError

mcp = MCPServer("MCPlayer_Server")

MUSIC_FILE = os.environ.get(key="MUSIC_FILE", default="albums.json")

ITEMS_FILE = Path(__file__).resolve().parent / MUSIC_FILE
_lock = threading.Lock()

SOLOIST_LOG = Path(__file__).resolve().parent / "soloist.log"
_soloist_proc: subprocess.Popen | None = None


class Track(BaseModel):
    name: str = Field(description="Common name of the track for internal use. It is not mandatory to match the official name of the track")
    uri: str = Field(description="Spotify's URI for the track. Must always start with 'spotify:track:' prefix")


class Album(BaseModel):
    name: str
    artist: str
    uri: str
    tracks: list[Track]


def _load_albums() -> list[Album]:
    """Load items.json (a list of {id: description} objects) into a dict."""
    if not ITEMS_FILE.exists():
        return []
    with ITEMS_FILE.open("r", encoding="utf-8") as f:
        content = f.read().strip()
    data = json.loads(content) if content else []
    albums: list[Album] = []
    for entry in data:
        if not isinstance(entry, dict):
            print(entry)
            raise ValueError(
                f"Invalid {MUSIC_FILE}: expected objects {Album.model_json_schema()} like, got {entry!r}"
            )
        try:
            albums.append(
                Album(
                    name=entry["name"],
                    artist=entry["artist"],
                    uri=entry["uri"],
                    tracks=entry["tracks"],
                )
            )
        except ValidationError as err:
            print(f"Validation error for item {entry}: {err}")
    return albums


def _save_album(album: Album) -> None:
    """Persist one album to the albums file."""
    albums = _load_albums()
    albums.append(album)
    with ITEMS_FILE.open("w", encoding="utf-8") as f:
        json.dump(
            [saved_album.model_dump() for saved_album in albums],
            f,
            indent=2,
            ensure_ascii=False,
        )


@mcp.tool()
def create_album(album: Album) -> str:
    """Crear y almacenar un nuevo álbum"""
    with _lock:
        albums = _load_albums()
        for a in albums:
            if album.name == a.name:
                return f"Error: Álbum con nombre'{album.name}' ya existe."
        _save_album(album)
    return f"Álbum '{album.name}' creado exitosamente."

@mcp.tool()
def get_album_by_name(name: str, include_tracks: bool = True) -> str:
    """Buscar y leer un álbum mediante una coincidencia parcial del nombre"""
    albums = _load_albums()
    for a in albums:
        if name.lower() in a.name.lower():
            if include_tracks:
                return f"Álbum encontrado:\n{a.model_dump_json()}"
            else:
                return f"Álbum encontrado:\n{a.model_dump_json(exclude={"tracks"})}"

    return f"El álbum no pudo ser encontrado."

@mcp.tool()
def get_album_by_uri(uri: str, include_tracks: bool = True) -> str:
    """Buscar y leer un álbum mediante una coincidencia exacta del URI"""
    albums = _load_albums()
    for a in albums:
        if uri.lower() == a.uri.lower():
            if include_tracks:
                return f"Álbum encontrado:\n{a.model_dump_json()}"
            else:
                return f"Álbum encontrado:\n{a.model_dump_json(exclude={"tracks"})}"

    return f"El álbum no pudo ser encontrado."

def play_album(uri: str) -> str:
    """Reproduce un álbum mediante su URI de Spotify"""
    if not uri.startswith("spotify:album:"):
        return f"Error: El URI proporcionado tiene un formato incorrecto."

    

def run_soloist_ctl_command(command_args: list[str]):
    args=["soloist", "ctl"]

    for a in command_args:
        args.append(a)

    try:
        proc = subprocess.run(
            args,
            check=True
        )

        return proc.stdout
    except:
        print()
    

@mcp.tool()
def start_soloist() -> str:
    """Start the Soloist (Spotify CLI player) process in the background"""
    global _soloist_proc

    with _lock:
        if _soloist_proc is not None and _soloist_proc.poll() is None:
            return f"Soloist is already running (pid {_soloist_proc.pid})."

        api_key = os.environ.get("SOLOIST_API_KEY")
        if not api_key:
            return "Error: SOLOIST_API_KEY is not set."

        log = SOLOIST_LOG.open("wb")
        try:
            proc = subprocess.Popen(
                [
                    "soloist",
                    "--device-name",
                    "Soloist-ERICKPC25",
                    "--api-key",
                    api_key,
                    "--ws",
                    "127.0.0.1:0",
                ],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        except FileNotFoundError:
            return "Error: 'soloist' executable was not found in PATH."
        except OSError as err:
            return f"Error: could not launch soloist: {err}"
        finally:
            log.close()  # the child keeps its own handle

        try:
            code = proc.wait(timeout=3)  # grace period to catch immediate failures
        except subprocess.TimeoutExpired:
            _soloist_proc = proc
            return f"Soloist started successfully (pid {proc.pid})."

        output = SOLOIST_LOG.read_text(encoding="utf-8", errors="replace")[-1000:]
        return f"Error: soloist exited immediately with code {code}.\n{output}"


@mcp.tool()
def stop_soloist() -> str:
    """Stop the Soloist process started by start_soloist"""
    global _soloist_proc

    with _lock:
        if _soloist_proc is None or _soloist_proc.poll() is not None:
            _soloist_proc = None
            return "Soloist is not running."
        _soloist_proc.terminate()
        _soloist_proc = None
        return "Soloist stopped."


@mcp.tool()
def get_local_datetime() -> str:
    """Get the current datetime in the server's timezone"""
    return datetime.now().isoformat()


if __name__ == "__main__":
    SERVER_TRANSPORT = os.environ.get(key="SERVER_TRANSPORT", default="http")
    SERVER_HOST = os.environ.get(key="SERVER_HOST", default="127.0.0.1")
    SERVER_PORT = int(os.environ.get(key="SERVER_PORT", default="8000"))

    if SERVER_TRANSPORT not in ["http", "stdio"]:
        raise Exception('El valor de SERVER_TRANSPORT debe ser "http" o "stdio"')

    if SERVER_TRANSPORT == "http":
        mcp.run(transport="streamable-http", host=SERVER_HOST, port=SERVER_PORT)
    else:
        mcp.run()
