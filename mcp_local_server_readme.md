# MCP-LOCAL-SERVER

Servidor **MCP** local en **Python** con herramientas para:

* `pdf_extract`: extrae **texto** y **tablas** desde PDFs locales
* `data_profile`: perfila **CSV/Excel/Parquet** (filas, columnas, memoria, preview)
* `ts_forecast`: pronóstico **simple** de series temporales con fecha
* `report_generate`: genera **reportes HTML y PDF** (tablas + gráficos)
* `llm_chat`: chat con **Llama** vía **Ollama** (endpoint OpenAI-compatible)
* `project_scaffold`: genera un **proyecto base** (archivos + git init + commit)

Incluye un **cliente demo** (`demo.py`) que orquesta todo y un **chat CLI** (`cli.py`) con **contexto** de conversación.
El servidor habla **JSON-RPC 2.0** por stdin/stdout (estilo MCP).

## 📋 Requisitos

* **Python 3.10+**
* **Ollama** en local y un modelo Llama (ej: `llama3.2:3b`)
* Dependencias del sistema (solo para exportar PDF con WeasyPrint):
  * **macOS:** `brew install pango cairo gdk-pixbuf libffi`
  * **Linux:** instala paquetes equivalentes (pango, cairo, gdk-pixbuf, libffi)

## ⚙️ Instalación

```bash
git clone https://github.com/<tu-usuario>/MCP-LOCAL-SERVER.git
cd MCP-LOCAL-SERVER

python -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\activate    # Windows (PowerShell)

pip install -r requirements.txt
```

### Variables de entorno

Crea tu archivo `.env` (o copia del ejemplo):

```bash
cp .env.example .env
```

Contenido recomendado:

```env
OPENAI_API_BASE=http://localhost:11434/v1
OPENAI_API_KEY=ollama
LLM_MODEL=llama3.2:3b
LLM_SYSTEM_PROMPT_PATH=prompts/system_llm.txt
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=120
```

El **system prompt** principal está en `prompts/system_llm.txt` y es fácil de modificar.

## 🦙 Modelo Llama con Ollama

**Arranca el servidor:**

```bash
ollama serve
```

**Descarga el modelo (ejemplo 3B):**

```bash
ollama pull llama3.2:3b
```

## 🚀 Uso rápido

### 1) Demo end-to-end (genera reporte)

```bash
python demo.py
```

**Qué hace:**
* Lee `samples/informe.pdf` y extrae texto/tablas
* Perfila `samples/datos.csv`
* Calcula forecast simple de `produccion`
* Pregunta al LLM un resumen del servidor
* Genera un **reporte** en `reports/` (HTML o PDF)

### 2) Chat CLI con contexto

```bash
python -u cli.py
```

**Comandos dentro del CLI:**

```bash
/tools               # lista herramientas MCP
/new                 # reinicia el contexto
/save [archivo.md]   # guarda transcript (default: reports/chat.md)
/call NAME {json}    # llama cualquier tool con JSON (ej: report_generate)
/help                # ayuda
/exit                # salir
```

**Ejemplo `/call` simple:**

```bash
/call report_generate {"title":"Demo","sections":["Hola"],"format":"pdf"}
```

### 3) Generar un proyecto base (scaffold)

La tool `project_scaffold` crea una estructura mínima de app, opcionalmente con git init y primer commit:

```bash
/call project_scaffold {"dir":"scaffolds/demo_app","name":"Demo App","requirements":["orjson","pandas"],"with_git":true,"python_pkg":true,"package_name":"demo"}
```

**Esto crea:**
* `scaffolds/demo_app/src/demo/__init__.py`
* `.gitignore`, `requirements.txt`, `main.py`, `README.md`
* Repo git con commit inicial

**Prueba rápida:**

```bash
cd scaffolds/demo_app
python3 main.py
# Hola desde Demo App!
```

## 🔌 MCP externos (opcional)

Puedes arrancar el CLI conectándolo a MCPs externos (Filesystem y Git) usando variables de entorno:

```bash
FS_MCP_CMD="python3 fs_mcp_local.py" \
GIT_MCP_CMD="python3 git_mcp_local.py" \
python3 -u cli.py
```

**Dentro del CLI:**

Listar tools del FileSystem MCP:

```bash
/fs.rpc {"method":"tools/list"}
```

Crear carpeta y un archivo:

```bash
/fs.call makeDir {"path":"demo_repo"}
/fs.call writeFile {"path":"demo_repo/README.md","text":"# Repo via MCP\n"}
```

Inicializar repo git y hacer commit:

```bash
/git.call init {"dir":"demo_repo"}
/git.call add {"dir":"demo_repo","files":["README.md"]}
/git.call commit {"dir":"demo_repo","message":"init repo via MCP"}
/git.call log {"dir":"demo_repo","n":5}
```

## 📊 Logs y artefactos

* **Artefactos** (reportes y gráficos): `reports/`
* **Log MCP** (JSONL): `reports/mcp.log.jsonl`

Cada línea incluye: `ts`, `method`, `ok`, `duration_ms`, `tool`, `args`, `result_size`, `error`.

Ver los últimos eventos:

```bash
tail -n 20 reports/mcp.log.jsonl
```

## 📂 Estructura del proyecto

```
MCP-LOCAL-SERVER/
├── prompts/
│   └── system_llm.txt
├── reports/                 # artefactos (pdf/html/png, log jsonl)
├── samples/
│   ├── informe.pdf
│   └── datos.csv
├── src/
│   ├── tools/
│   │   ├── data_profile.py
│   │   ├── llm_chat.py
│   │   ├── pdf_extract.py
│   │   ├── project_scaffold.py
│   │   ├── report_generate.py
│   │   └── ts_forecast.py
│   └── util/
│       ├── mcp_process.py
│       └── registry.py
├── .env.example
├── .gitignore
├── requirements.txt
├── main.py                  # servidor MCP (JSON-RPC)
├── demo.py                  # demo orquestada
├── cli.py                   # chatbot CLI con contexto
├── fs_mcp_local.py          # (opcional) MCP de filesystem
└── git_mcp_local.py         # (opcional) MCP de git
```

## 🔧 Troubleshooting

### **Ollama no responde / timeout**
* Asegúrate de tener `ollama serve` corriendo
* Verifica la versión con `curl -s http://localhost:11434/api/version`
* Checa `ollama list` y el nombre en `LLM_MODEL`

### **Falla exportación a PDF**
* Instala dependencias del sistema (ver requisitos)
* Reinstala Python deps: `pip install weasyprint`

### **Permisos de archivos**
* Asegura que `reports/` exista y sea escribible (el código la crea si falta)

## 📦 Dependencias principales

Inclúyelas en `requirements.txt` (ajusta versiones si necesitas):

```
python-dotenv
openai
orjson
pandas
matplotlib
weasyprint
PyMuPDF
```

## 📄 Licencia

MIT — ver `LICENSE`.

## 👨‍💻 Créditos

**Proyecto académico:** MCP Server Local en Python (Parte 1)  
**Autor:** Jorge Luis Lopez 221038