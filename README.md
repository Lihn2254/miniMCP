# miniMCP

A lightweight project that shows how to connect a local AI model (using [Ollama](https://ollama.com/)) to custom tools through the **Model Context Protocol** (MCP).

The AI acts as a music assistant. It can manage a small album and track library (stored in a JSON file) and control playback through Soloist (a Spotify CLI player).

## Project Structure

* **`server/server.py`**: The MCP server, built with `MCPServer`. It exposes the following tools:
  * **Albums**: `register_album`, `get_album_by_name`, `get_album_by_uri`, `get_all_albums`, `update_album`, `delete_album`
  * **Tracks**: `register_track`, `get_track_by_name`, `get_track_by_uri`, `update_track`, `delete_track`
  * **Soloist process**: `start_soloist`, `stop_soloist`, `activate_soloist`, `get_status`
  * **Playback**: `manage_playback` (`play`, `pause`, `next`, `prev`, `seek`), `set_volume`, `set_shuffle`, `set_repeat`, `get_now_playing`, `get_queue`, `add_to_queue`
  * **Utilities**: `get_local_datetime`

* **`server/helpers.py`**: Helpers for reading and writing the album file and for running Soloist commands.

* **`server/schemas.py`**: Pydantic models (`Album`, `Track`).

* **`server/config.py`**: Settings loaded from the environment / `.env` file.

* **`server/albums.json`**: The album and track library.

* **`client/stdio_client.py`** / **`client/http_client.py`**: Terminal clients. The first connects to the MCP server through standard input/output (`stdio`), the second through HTTP (`streamable-http`). Both load the available tools and start a chat loop between the user and the Ollama LLM.

* **`requirements.txt`**: The project's main dependencies.

## Requirements

Before starting, make sure you have:
1. **Python 3.12+**
2. **Ollama** installed and running on your machine.
3. The model this repository uses, `gemma4:e4b` by default. You can download it with:
   ```bash
   ollama run gemma4:e4b
   ```
4. **Soloist** available in your `PATH`, and a `SOLOIST_API_KEY` (set in `.env` or the environment; the server requires it to start). Stopping the server does not stop Soloist: when the server starts, it looks for a Soloist that is already running and takes control of it, so music keeps playing across server restarts. Use the `stop_soloist` tool to stop it.

## Installation

1. Clone the repository and move into its folder:
   ```bash
   git clone <repo-url> miniMCP
   cd miniMCP
   ```

2. Create and activate a virtual environment (optional but highly recommended):
   ```bash
   python -m venv .venv
   # On Windows:
   .\.venv\Scripts\activate
   # On macOS/Linux:
   source .venv/bin/activate
   ```

3. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Copy `.env.example` to `.env` and adjust it to your setup.

## Configuration

Settings are read from environment variables or from the `.env` file in the project root.

| Variable | Used by | Description | Default |
|---|---|---|---|
| `SERVER_TRANSPORT` | server | `http` or `stdio` | `http` |
| `SERVER_HOST` | server | Host to bind to when using HTTP | `127.0.0.1` |
| `SERVER_PORT` | server | Port to bind to when using HTTP | `8000` |
| `SERVER_PATH` | server | Route of the MCP endpoint when using HTTP (normalized: `mcp/` becomes `/mcp`) | `/mcp` |
| `MUSIC_FILE` | server | Album library file (relative paths are resolved against `server/`) | `server/albums.json` |
| `SOLOIST_API_KEY` | server | API key used to start Soloist | none (**required**; the server will not start without it) |
| `SERVER_URL` | HTTP client | URL of the MCP server. Must match `SERVER_HOST`, `SERVER_PORT` and `SERVER_PATH` | `http://127.0.0.1:8000/mcp` |
| `MODEL_NAME` | clients | Ollama model to use | `gemma4:e4b` |
| `LLM_BASE_URL` | HTTP client | URL of the Ollama server | `http://127.0.0.1:11434` |
| `NUM_CTX` | HTTP client | Context window size | `16384` |
| `AUTO_START_OLLAMA` | HTTP client | Start Ollama automatically (`True`/`False`); only applies if `LLM_BASE_URL` is local | `False` |

The HTTP client prints the model and the LLM URL at startup, and the MCP server URL once connected.

## Validation

* Albums and tracks are validated by the Pydantic models: `name` and `artist` cannot be empty, and URIs must start with `spotify:album:` / `spotify:track:`.
* Albums with a duplicate URI or name are rejected.
* Tool parameters are described in the generated schemas, and numeric ones are bounded (`volume` 0-100, `get_queue` `limit` 1-50, `seek` `ms` >= 0).
* If `albums.json` contains an invalid entry, the tools report an error instead of skipping it, so no data is silently lost.

## Usage

There are two clients, depending on the MCP transport you want to use.

**stdio** (the client launches the server itself):
```bash
python client/stdio_client.py
```

**HTTP** (streamable HTTP; the server runs separately):
```bash
# Terminal 1: server at http://127.0.0.1:8000/mcp
python server/server.py

# Terminal 2: client
python client/http_client.py
```
*Type your questions to the model directly in the console.*

---

## Example Interaction

You can try telling the AI:
* *"Create an album called 'For Lovers' by Lamp with the URI 'spotify:album:0gwS2D9sukMLXNvleEnYr2'"*
* *"Add the track 'Rainy Tapestry' to that album"*
* *"Find the track 'moon'"*
* *"Start Soloist and play that album"*
* *"Set the volume to 40, turn on shuffle and show me the queue"*

The AI will run the tools in `server/server.py` automatically, so you don't need to write the code or the calls yourself.
