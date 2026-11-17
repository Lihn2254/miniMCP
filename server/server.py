import os, subprocess

from mcp.server.mcpserver import MCPServer
import threading
from datetime import datetime


from server.helpers import _load_albums, _save_album, run_soloist_ctl_command
from server.schemas import Album

mcp = MCPServer("MCPlayer_Server")


_lock = threading.Lock()
_soloist_proc: subprocess.Popen | None = None


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


# def play_album(uri: str) -> str:
#     """Reproduce un álbum mediante su URI de Spotify"""
#     if not uri.startswith("spotify:album:"):
#         return f"Error: El URI proporcionado tiene un formato incorrecto."


@mcp.tool()
def start_soloist() -> str:
    """Start the Soloist (Spotify CLI player) process in the background"""
    global _soloist_proc

    with _lock:
        if _soloist_proc is not None and _soloist_proc.poll() is None:
            return f"Soloist is already running (pid {_soloist_proc.pid})."

        proc, message = run_soloist_ctl_command(["--ws", "127.0.0.1:0"])
        if proc is not None:
            _soloist_proc = proc
        return message


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
