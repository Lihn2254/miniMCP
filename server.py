from mcp.server.mcpserver import MCPServer
import json
import subprocess
import threading
from pathlib import Path

mcp = MCPServer("CRUD_Demo_Server")

ITEMS_FILE = Path(__file__).resolve().parent / "items.json"
_lock = threading.Lock()


def _load_items() -> dict[str, str]:
    """Load items.json (a list of {id: description} objects) into a dict."""
    if not ITEMS_FILE.exists():
        return {}
    with ITEMS_FILE.open("r", encoding="utf-8") as f:
        content = f.read().strip()
    data = json.loads(content) if content else []
    items: dict[str, str] = {}
    for entry in data:
        if not isinstance(entry, dict):
            raise ValueError(
                f"Invalid items.json: expected objects like {{\"1\": \"Description\"}}, got {entry!r}"
            )
        for key, value in entry.items():
            items[str(key)] = value
    return items


def _save_items(items: dict[str, str]) -> None:
    """Persist items to items.json as a list of {id: description} objects."""
    with ITEMS_FILE.open("w", encoding="utf-8") as f:
        json.dump([{k: v} for k, v in items.items()], f, indent=2, ensure_ascii=False)


@mcp.tool()
def create_item(item_id: str, content: str) -> str:
    """Create a new item in items.json."""
    with _lock:
        items = _load_items()
        if item_id in items:
            return f"Error: Item '{item_id}' already exists."
        items[item_id] = content
        _save_items(items)
    return f"Success: Created item '{item_id}'."

@mcp.tool()
def read_item(item_id: str) -> str:
    """Read an item from items.json."""
    items = _load_items()
    if item_id not in items:
        return f"Error: Item '{item_id}' not found."
    return f"Item '{item_id}': {items[item_id]}"

@mcp.tool()
def read_multiple_items(items_id: list[str]) -> str:
    """Read multiple items from items.json at once."""
    items = _load_items()
    results = []
    for item_id in items_id:
        if item_id not in items:
            results.append(f"Error: Item '{item_id}' not found.")
        else:
            results.append(f"Item '{item_id}': {items[item_id]}")
    return "\n".join(results)

@mcp.tool()
def read_all_items() -> str:
    """Read all items from items.json at once."""
    items = _load_items()
    return "\n".join(f"Item '{k}': {v}" for k, v in items.items())

@mcp.tool()
def update_item(item_id: str, new_content: str) -> str:
    """Update an existing item in items.json."""
    with _lock:
        items = _load_items()
        if item_id not in items:
            return f"Error: Item '{item_id}' not found. Cannot update."
        items[item_id] = new_content
        _save_items(items)
    return f"Success: Updated item '{item_id}'."

@mcp.tool()
def delete_item(item_id: str) -> str:
    """Delete an item from items.json."""
    with _lock:
        items = _load_items()
        if item_id not in items:
            return f"Error: Item '{item_id}' not found. Cannot delete."
        del items[item_id]
        _save_items(items)
    return f"Success: Deleted item '{item_id}'."

@mcp.tool()
def run_shell_command(args: str):
    """Execute a shell command on Windows"""
    try:
        result = subprocess.run(
            args,
            shell=True,
            capture_output=True,
            text=True,
            check=True
        )

        return result.stdout
    except Exception as err:
        return err

if __name__ == "__main__":
    import os

    SERVER_TRANSPORT = os.environ.get(key="SERVER_TRANSPORT", default="http")
    SERVER_HOST = os.environ.get(key="SERVER_HOST", default="127.0.0.1")
    SERVER_PORT = int(os.environ.get(key="SERVER_PORT", default="8000"))

    if SERVER_TRANSPORT not in ["http", "stdio"]:
        raise Exception('El valor de SERVER_TRANSPORT debe ser "http" o "stdio"')

    if SERVER_TRANSPORT == "http":
        mcp.run(transport="streamable-http", host=SERVER_HOST, port=SERVER_PORT)
    else:
        mcp.run()