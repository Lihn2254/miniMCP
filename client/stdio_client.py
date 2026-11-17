import asyncio
import os
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import ollama
from dotenv import load_dotenv

load_dotenv()

# Configuración
MODEL_NAME = os.environ.get(key="MODEL_NAME", default="gemma4:e4b")
SERVER_SCRIPT = "server.py"

async def run_mcp_client():
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[SERVER_SCRIPT]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Conectado al Servidor MCP.")

            mcp_tools = await session.list_tools()
            # Imprimir respuesta JSON-RPC de list_tools
            # print("\n--- RAW MCP TOOLS RESPONSE ---")
            # print(mcp_tools.model_dump_json(indent=2))
            
            ollama_tools = []
            for tool in mcp_tools.tools:
                ollama_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema
                    }
                })

            print(f"Cargadas {len(ollama_tools)} herramientas del servidor. Iniciando chat...")
            
            # Mensaje inicial para dar contexto al modelo
            messages = [
                {
                    "role": "system", 
                    "content": ("""Eres un asistente de IA útil conectado a un sistema de base de datos local a través del Protocolo de Contexto de Modelos (MCP). 
                                Puedes crear, leer, actualizar y eliminar elementos.

                                ### Guidelines
                                - Actúa siempre de forma profesional y concisa. Si no sabes algo, utiliza tus herramientas para averiguarlo.
                                - Todas tus respuestas deben ser escritas en español, excepto los fragmentos de tu respuesta que incluyan contenido recuperado de los elementos de la base de datos.
                                - Dirígete al usuario con el pronombre 'tú'.
                                - Si requieres crear un nuevo elemento en la lista y el usuario no te proporciona un ID, tú debes crealo.
                                - Utiliza un formato de texto plano para tus respuestas, ya que la salida no cuenta con soporte para formado .md.""")
                }
            ]
            
            while True:
                try:
                    user_input = input("\nTú > ")
                except EOFError:
                    break
                if user_input.lower() in ['quit', 'exit', 'salir']:
                    break

                messages.append({"role": "user", "content": user_input,})

                response = ollama.chat(
                    model=MODEL_NAME,
                    messages=messages,
                    tools=ollama_tools
                )

                messages.append(response['message'])

                if response['message'].get('tool_calls'):
                    for tool_call in response['message']['tool_calls']:
                        func_name = tool_call['function']['name']
                        func_args = tool_call['function']['arguments']
                        
                        print(f"  [IA ejecutando herramienta: {func_name}({func_args})]")
                        
                        mcp_result = await session.call_tool(func_name, func_args)

                        if mcp_result.content:
                            first_item = mcp_result.content[0]
                            text_value = getattr(first_item, "text", None)
                            result_text = text_value if isinstance(text_value, str) else str(first_item)
                        else:
                            result_text = "Sin respuesta"
                        print(f"  [Respuesta de la herramienta: {result_text}]")

                        messages.append({
                            "role": "tool",
                            "content": result_text,
                            "name": func_name
                        })

                    final_response = ollama.chat(
                        model=MODEL_NAME,
                        messages=messages
                    )
                    messages.append(final_response['message'])
                    print(f"\nGemma4 > {final_response['message']['content']}")
                else:
                    # Respuesta normal de texto sin uso de herramientas
                    print(f"\nGemma4 > {response['message']['content']}")

if __name__ == "__main__":
    asyncio.run(run_mcp_client())