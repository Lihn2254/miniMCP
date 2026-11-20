import json
import os
import subprocess

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError


from schemas import Album
from config import get_settings

music_file = get_settings().MUSIC_FILE

SOLOIST_CTL_TIMEOUT = 10  # seconds


def execute_soloist_command(command_args: list[str], **popen_kwargs) -> subprocess.Popen:
    """Run `soloist <command_args>` and return the started process.

    This is the only place that spawns the soloist subprocess. `popen_kwargs`
    are forwarded to `subprocess.Popen`. Errors such as FileNotFoundError or
    OSError propagate to the caller.
    """
    return subprocess.Popen(["soloist", *command_args], **popen_kwargs)


def run_soloist_ctl_command(command_args: list[str]) -> tuple[int, str]:
    """Run `soloist ctl <command_args>` and wait for it to finish.

    "ctl" is always prepended, so pass only the ctl subcommand and its args.
    Returns `(returncode, output)`; on failure to run, returncode is -1 and
    output describes the error.
    """
    try:
        proc = execute_soloist_command(
            ["ctl", *command_args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError:
        return -1, "Error: 'soloist' executable was not found in PATH."
    except OSError as err:
        return -1, f"Error: could not run soloist ctl: {err}"

    try:
        output, _ = proc.communicate(timeout=SOLOIST_CTL_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return -1, f"Error: soloist ctl timed out after {SOLOIST_CTL_TIMEOUT}s."
    return proc.returncode, output.strip()


def start_soloist() -> tuple[subprocess.Popen | None, str]:
    """Launch Soloist in the background, redirecting its output to the
    configured log file.

    Returns `(process, message)`. `process` is None when the launch failed, in
    which case `message` describes the error; otherwise `message` is a success
    message.
    """
    settings = get_settings()
    api_key = settings.SOLOIST_API_KEY
    soloist_log = settings.SOLOIST_LOG

    log = soloist_log.open("wb")
    try:
        proc = execute_soloist_command(
            [
                "--device-name",
                settings.DEVICE_NAME,
                "--api-key",
                api_key,
                "--ws",
                "127.0.0.1:0",
                "--initial-volume",
                "100"
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            # Detach Soloist from the server's console/terminal so that stopping
            # the server (e.g. Ctrl+C) does not stop playback.
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            start_new_session=(os.name != "nt"),
        )
    except FileNotFoundError:
        return None, "Error: 'soloist' executable was not found in PATH."
    except OSError as err:
        return None, f"Error: could not launch soloist: {err}"
    finally:
        log.close()

    try:
        code = proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        return proc, f"Soloist started successfully (pid {proc.pid})."

    output = soloist_log.read_text(encoding="utf-8", errors="replace")[-1000:]
    return None, f"Error: soloist exited immediately with code {code}.\n{output}"


def _load_albums() -> list[Album]:
    """Load the albums file (a JSON list of album objects) into a list of
    `Album` models.

    Raises `ToolError` (so the message reaches the client as an MCP `isError`
    result; any other exception is reduced to a generic message) if the file is malformed or any entry is invalid. Invalid
    entries are never skipped: every write rewrites the whole file, so skipping
    them would silently delete them from disk.
    """

    if not music_file.exists():
        return []
    with music_file.open("r", encoding="utf-8") as f:
        content = f.read().strip()
    try:
        data = json.loads(content) if content else []
    except json.JSONDecodeError as err:
        raise ToolError(f"Invalid music file [{music_file}]: not valid JSON ({err})") from err
    if not isinstance(data, list):
        raise ToolError(f"Invalid music file [{music_file}]: expected a JSON list of albums.")

    albums: list[Album] = []
    for index, entry in enumerate(data):
        try:
            albums.append(Album.model_validate(entry))
        except ValidationError as err:
            raise ToolError(
                f"Invalid music file [{music_file}]: entry #{index} is not a valid album "
                f"({err.error_count()} error(s)): {err}. Fix the file manually; nothing was modified."
            )
    return albums


def _save_album(album: Album) -> None:
    """Append one album to the albums file."""
    albums = _load_albums()
    albums.append(album)
    _write_albums(albums)


def _write_albums(albums: list[Album]) -> None:
    """Overwrite the albums file with the given list of albums."""
    with music_file.open("w", encoding="utf-8") as f:
        json.dump(
            [saved_album.model_dump() for saved_album in albums],
            f,
            indent=2,
            ensure_ascii=False,
        )
