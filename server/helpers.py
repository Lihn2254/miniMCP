import json
import os
import subprocess

from pydantic import ValidationError

from server.config import get_settings
from server.schemas import Album

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
    api_key = os.environ.get("SOLOIST_API_KEY")
    if not api_key:
        return None, "Error: SOLOIST_API_KEY is not set."

    settings = get_settings()
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
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
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
    """Load items.json (a list of {id: description} objects) into a dict."""

    if not music_file.exists():
        return []
    with music_file.open("r", encoding="utf-8") as f:
        content = f.read().strip()
    data = json.loads(content) if content else []
    albums: list[Album] = []
    for entry in data:
        if not isinstance(entry, dict):
            print(entry)
            raise ValueError(
                f"Invalid music file [{music_file}]: expected objects {Album.model_json_schema()} like, got {entry!r}"
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
    with music_file.open("w", encoding="utf-8") as f:
        json.dump(
            [saved_album.model_dump() for saved_album in albums],
            f,
            indent=2,
            ensure_ascii=False,
        )
