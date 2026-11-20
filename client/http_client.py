import asyncio
import os, subprocess
import ipaddress
from urllib.parse import urlparse
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import ollama
from dotenv import load_dotenv

load_dotenv()

MODEL_NAME = os.environ.get(key="MODEL_NAME", default="gemma4:e4b")
SERVER_URL = os.environ.get(key="SERVER_URL", default="http://127.0.0.1:8000/mcp")
LLM_BASE_URL = os.environ.get(key="LLM_BASE_URL", default="http://127.0.0.1:11434")
NUM_CTX = int(os.environ.get(key="NUM_CTX", default="16384"))
ENABLE_THINKING = bool(os.environ.get(key="ENABLE_THINKING", default="16384") == "True")
AUTO_START_OLLAMA = bool(os.environ.get(key="AUTO_START_OLLAMA", default="False") == "True")

MAX_TOOL_ROUNDS = 25

SYSTEM_PROMPT = {
                    "role": "system",
                    "content": (
                        """Eres un asistente de música conectado, a través del Protocolo de Contexto de Modelos (MCP), a una biblioteca local de álbumes y canciones y a Soloist, un reproductor de Spotify.
                                Puedes crear, leer, actualizar y eliminar álbumes y canciones de la biblioteca, y controlar la reproducción con Soloist.

                                ### Guidelines
                                - Actúa siempre de forma profesional y concisa. Si no sabes algo, utiliza tus herramientas para averiguarlo.
                                - Todas tus respuestas deben ser escritas en español, excepto los fragmentos de tu respuesta que incluyan contenido recuperado de la biblioteca (nombres de álbumes, artistas y canciones).
                                - Dirígete al usuario con el pronombre 'tú'.
                                - Utiliza un formato de texto plano para tus respuestas, ya que la salida no cuenta con soporte para formado .md.
                                - Cuando el usuario indique una hora o tiempo, asume siempre que está haciendo referencia a su propia zona horaria.
                        """
                    ),
                }

def describe_error(err: BaseException) -> str:
    """Human-readable cause of an error, unwrapping exception groups (anyio
    wraps connection failures in one) and Ollama API errors."""
    if isinstance(err, BaseExceptionGroup):
        return "; ".join(describe_error(e) for e in err.exceptions)
    if isinstance(err, ollama.ResponseError):
        return f"Ollama respondió con error {err.status_code}: {err.error}"
    detail = str(err)
    return f"{type(err).__name__}: {detail}" if detail else type(err).__name__


async def call_mcp_tool(session: ClientSession, name: str, args: dict) -> str:
    """Call an MCP tool and return its result as text for the `tool` message.

    Failures never propagate: they are returned as text, so the model can read
    the error and explain it (or retry) instead of the chat dying.
    """
    try:
        mcp_result = await session.call_tool(name, args)
    except Exception as err:
        return f"Error: no se pudo ejecutar la herramienta ({describe_error(err)})"

    if mcp_result.content:
        first_item = mcp_result.content[0]
        text_value = getattr(first_item, "text", None)
        result_text = text_value if isinstance(text_value, str) else str(first_item)
    else:
        result_text = ""
    if not result_text.strip():
        result_text = "Sin resultados"
    if mcp_result.is_error:
        result_text = f"Error: {result_text}"
    return result_text


async def run_turn(
    llm_client: ollama.AsyncClient,
    session: ClientSession,
    messages: list,
    ollama_tools: list,
) -> str:
    """Answer the last user message in `messages`, running the tool-call cycle:
    ask the LLM; while it requests tools, call them through MCP, add the results
    as `tool` messages and ask again. Returns the final reply text.

    Appends to `messages` as it goes. Errors propagate to the caller, which is
    responsible for discarding the partial turn.
    """
    for _ in range(MAX_TOOL_ROUNDS):
        response = await llm_client.chat(
            model=MODEL_NAME,
            messages=messages,
            tools=ollama_tools,
            think=ENABLE_THINKING,
            options={"num_ctx": NUM_CTX},
        )
        message = response["message"]
        messages.append(message)

        if not message.get("tool_calls"):
            return message.get("content") or "(sin respuesta)"

        for tool_call in message["tool_calls"]:
            func_name = tool_call["function"]["name"]
            func_args = tool_call["function"]["arguments"]

            print(f"  [IA ejecutando herramienta: {func_name}({func_args})]")
            result_text = await call_mcp_tool(session, func_name, func_args)
            print(f"  [Respuesta de la herramienta: {result_text}]")

            messages.append(
                {"role": "tool", "content": result_text, "tool_name": func_name}
            )

    # The model kept requesting tools. Its last requests were executed but never
    # interpreted, so ask once more, without tools, for an answer based on what
    # was obtained. The nudge is sent only in this call, not stored in the history.
    print(
        f"  [Aviso: se alcanzó el límite de {MAX_TOOL_ROUNDS} rondas de "
        "herramientas; se pide al modelo que responda con lo obtenido]"
    )
    nudge = {
        "role": "user",
        "content": (
            "Has alcanzado el límite de llamadas a herramientas. Responde ahora "
            "con la información obtenida e indica qué quedó pendiente."
        ),
    }
    response = await llm_client.chat(
        model=MODEL_NAME,
        messages=[*messages, nudge],
        think=ENABLE_THINKING,
        options={"num_ctx": NUM_CTX},
    )
    message = response["message"]
    messages.append(message)
    return message.get("content") or "(sin respuesta)"


async def run_mcp_client():
    ollama_process = None
    try:
        print()
        if AUTO_START_OLLAMA and is_agent_local():
            print("Cargando Ollama...")
            ollama_process = start_ollama()
            print("Ollama cargado")
        else:
            print("Ollama debe estar ejecutándose")
        print(f"\tModelo: {MODEL_NAME}\n\tURL del LLM: {LLM_BASE_URL}\n")

        llm_client = ollama.AsyncClient(host=LLM_BASE_URL)

        async with streamable_http_client(SERVER_URL) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                init_result = await session.initialize()

                system_prompt = dict(SYSTEM_PROMPT)
                if init_result.instructions:
                    system_prompt["content"] += (
                        "\n\n### Instrucciones del servidor (en inglés)\n"
                        + init_result.instructions
                    )

                print(
                    f"Conectado al Servidor MCP.\n\tURL: {SERVER_URL}"
                )

                mcp_tools = await session.list_tools()
                # Print the JSON-RPC response of list_tools
                # print("\n--- RAW MCP TOOLS RESPONSE ---")
                # print(mcp_tools.model_dump_json(indent=2))

                ollama_tools = []
                for tool in mcp_tools.tools:
                    print(f"Cargando herramienta {tool.name}...")
                    ollama_tools.append(
                        {
                            "type": "function",
                            "function": {
                                "name": tool.name,
                                "description": tool.description,
                                "parameters": tool.input_schema,
                            },
                        }
                    )

                print(
                    f"Cargadas {len(ollama_tools)} herramientas del servidor. Iniciando chat..."
                )

                messages = [system_prompt]

                model_common_name = get_model_common_name()

                while True:
                    try:
                        user_input = input("\nTú > ")
                    except (EOFError, KeyboardInterrupt):
                        break

                    if user_input.lower() in ["/quit", "/exit", "/salir"]:
                        break
                    elif user_input.lower() == '/clear':
                        messages = [system_prompt]
                        print('     Memoria de la conversación eliminada')
                        continue

                    # A failed query must not end the session or leave a half-done
                    # turn (e.g. tool calls without results) in the history.
                    history_len = len(messages)
                    messages.append({"role": "user", "content": user_input})
                    try:
                        reply = await run_turn(
                            llm_client, session, messages, ollama_tools
                        )
                    except Exception as err:
                        del messages[history_len:]
                        print(
                            f"\n[ERROR] No se pudo completar la consulta: {describe_error(err)}"
                            "\n        La consulta se descartó del historial; puedes intentarlo de nuevo."
                        )
                        continue

                    print(f"\n{model_common_name} > {reply}")
    except Exception as err:
        print(
            f"\n[ERROR] {describe_error(err)}"
            f"\n        Verifica que el servidor MCP esté en {SERVER_URL} "
            f"y que Ollama responda en {LLM_BASE_URL}."
        )
    finally:
        if ollama_process is not None:
            stop_ollama(ollama_process)


def get_model_common_name():
    return MODEL_NAME.split(":")[0].capitalize()

def start_ollama():
    try:
        return subprocess.Popen(
            args=["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as err:
        print("[ERROR] Failed to start Ollama server")
        raise err


def stop_ollama(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

def is_agent_local():
    try:
        url = LLM_BASE_URL if "://" in LLM_BASE_URL else f"//{LLM_BASE_URL}"
        hostname = urlparse(url).hostname
    except (TypeError, ValueError):
        return False

    if not hostname:
        return False

    hostname = hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True

    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False

if __name__ == "__main__":
    asyncio.run(run_mcp_client())
