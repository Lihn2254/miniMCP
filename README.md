# miniMCP

Un proyecto ligero que demuestra cómo implementar y conectar un modelo de IA local (usando [Ollama](https://ollama.com/)) con herramientas personalizadas a través del **Protocolo de Contexto de Modelos** (Model Context Protocol o MCP). 

En este proyecto, la IA actúa como un asistente de bases de datos que puede consultar y gestionar una base de datos en memoria utilizando operaciones CRUD (Crear, Leer, Actualizar, Eliminar).

## Estructura del Proyecto

* **`server.py`**: Es el servidor MCP creado con `FastMCP`. Mantiene una base de datos en memoria y expone herramientas (`tools`) para:
  * Crear elementos (`create_item`)
  * Leer elementos individuales (`read_item`)
  * Leer múltiples elementos a la vez (`read_multiple_items`)
  * Actualizar elementos (`update_item`)
  * Eliminar elementos (`delete_item`)

* **`client.py`**: Es el cliente que interactúa mediante la terminal. Se conecta al servidor MCP a través de los flujos de entrada/salida estándar (`stdio`), lee las herramientas disponibles y establece un ciclo de chat con el usuario y el LLM de Ollama (`gemma4:e4b`).

* **`requirements.txt`**: Archivo con las dependencias principales del proyecto.

## Requisitos y Dependencias

Antes de iniciar el proyecto, asegúrate de tener instalado:
1. **Python 3.10+**
2. **Ollama** instalado y ejecutándose en tu máquina.
3. El modelo que utiliza este repositorio, que por defecto es `gemma4:e4b`. Puedes descargarlo con el comando: 
   ```bash
   ollama run gemma4:e4b
   ```

## Instalación

1. Clona el repositorio y navega hasta su carpeta:
   ```bash
   git clone <url-del-repo> miniMCP
   cd miniMCP
   ```

2. Crea y activa un entorno virtual (opcional pero muy recomendado):
   ```bash
   python -m venv .venv
   # En Windows:
   .\.venv\Scripts\activate
   # En macOS/Linux:
   source .venv/bin/activate
   ```

3. Instala las dependencias necesarias:
   ```bash
   pip install -r requirements.txt
   pip install gradio
   ```

## Uso

El proyecto consta de la configuración Cliente/Servidor, pero el cliente se encarga de lanzar el servidor por sí mismo, así que solo necesitas ejecutar el cliente:
```bash
python client.py
```
*Escribe tus preguntas directamente en la consola.*

---

## Ejemplo de Interacción

Puedes probar decirle a la IA:
* *"Crea un elemento con el ID 'tarea1' y contenido 'Comprar leche'"*
* *"Muestra el contenido del área 'tarea1'"*
* *"Actualiza la 'tarea1' y dime que la leche debe ser descremada"*
* *"Lee los elementos 'tarea1' y 'tarea2'"*
* *"Borra el ID 'tarea1'"*

La IA ejecutará automáticamente las herramientas del `server.py` sin que tú debas escribir el código o las llamadas directamente.