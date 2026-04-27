from mcp.server.fastmcp import FastMCP

# Initialize the MCP Server
mcp = FastMCP("CRUD_Demo_Server")

# Our simple in-memory database
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
    # Run the server using standard input/output (the default for MCP)
    mcp.run()