from mcp.server.mcpserver import MCPServer

mcp = MCPServer("CRUD_Demo_Server")

database = {}

@mcp.tool()
def create_item(item_id: str, content: str) -> str:
    """Create a new item in the database."""
    if item_id in database:
        return f"Error: Item '{item_id}' already exists."
    database[item_id] = content
    return f"Success: Created item '{item_id}'."

@mcp.tool()
def read_item(item_id: str) -> str:
    """Read an item from the database."""
    if item_id not in database:
        return f"Error: Item '{item_id}' not found."
    return f"Item '{item_id}': {database[item_id]}"

@mcp.tool()
def read_multiple_items(items_id: list[str]) -> str:
    """Read multiple items from the database at once."""
    results = []
    for item_id in items_id:
        if item_id not in database:
            results.append(f"Error: Item '{item_id}' not found.")
        else:
            results.append(f"Item '{item_id}': {database[item_id]}")
    return "\n".join(results)

@mcp.tool()
def read_all_items() -> str:
    """Read all items from the database at once."""
    results = []
    for item_id, item_desc in database.items():
        results.append(f"Item '{item_id}': {item_desc}")
    return "\n".join(results)

@mcp.tool()
def update_item(item_id: str, new_content: str) -> str:
    """Update an existing item in the database."""
    if item_id not in database:
        return f"Error: Item '{item_id}' not found. Cannot update."
    database[item_id] = new_content
    return f"Success: Updated item '{item_id}'."

@mcp.tool()
def delete_item(item_id: str) -> str:
    """Delete an item from the database."""
    if item_id not in database:
        return f"Error: Item '{item_id}' not found. Cannot delete."
    del database[item_id]
    return f"Success: Deleted item '{item_id}'."

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