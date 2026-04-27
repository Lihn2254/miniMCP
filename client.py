import asyncio
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import ollama

# Configuration
MODEL_NAME = "gemma4:e4b"
SERVER_SCRIPT = "server.py"

async def run_mcp_client():
    # 1. Define how to connect to the MCP server
    server_params = StdioServerParameters(
        command=sys.executable, # Use the current Python interpreter
        args=[SERVER_SCRIPT]
    )

    # 2. Connect to the server via stdio
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection protocol
            await session.initialize()
            print("Connected to MCP Server.")

            # 3. Get available tools from the MCP server
            mcp_tools = await session.list_tools()
            
            # 4. Convert MCP tool schema to Ollama tool schema
            ollama_tools = []
            for tool in mcp_tools.tools:
                ollama_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema
                    }
                })

            print(f"Loaded {len(ollama_tools)} tools from server. Starting chat...")
            
            # 5. Interactive Chat Loop
            messages = []
            while True:
                try:
                    user_input = input("\nYou: ")
                except EOFError:
                    break
                if user_input.lower() in ['quit', 'exit', 'bye']:
                    break

                messages.append({"role": "user", "content": user_input,})

                # Call Ollama with the available tools
                response = ollama.chat(
                    model=MODEL_NAME,
                    messages=messages,
                    tools=ollama_tools
                )

                # Add the model's response to the conversation history
                messages.append(response['message'])

                # 6. Handle Tool Calls if the model decided to use one
                if response['message'].get('tool_calls'):
                    for tool_call in response['message']['tool_calls']:
                        func_name = tool_call['function']['name']
                        func_args = tool_call['function']['arguments']
                        
                        print(f"  [AI executing tool: {func_name}({func_args})]")
                        
                        # Execute the tool on the MCP server
                        mcp_result = await session.call_tool(func_name, func_args)
                        
                        # Extract text content safely (content can include non-text items)
                        if mcp_result.content:
                            first_item = mcp_result.content[0]
                            text_value = getattr(first_item, "text", None)
                            result_text = text_value if isinstance(text_value, str) else str(first_item)
                        else:
                            result_text = "No output"
                        print(f"  [Tool output: {result_text}]")

                        # Append the tool result back to the messages so Ollama knows the outcome
                        messages.append({
                            "role": "tool",
                            "content": result_text,
                            "name": func_name
                        })

                    # Call Ollama again so it can summarize the tool output
                    final_response = ollama.chat(
                        model=MODEL_NAME,
                        messages=messages
                    )
                    messages.append(final_response['message'])
                    print(f"\nOllama: {final_response['message']['content']}")
                else:
                    # Normal text response
                    print(f"\nOllama: {response['message']['content']}")

if __name__ == "__main__":
    asyncio.run(run_mcp_client())