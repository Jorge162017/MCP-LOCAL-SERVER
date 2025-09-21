# MCP-LOCAL-SERVER

Servidor **MCP** local en **Python** con herramientas para:

* `pdf_extract`: extrae **texto** y **tablas** desde PDFs locales
* `data_profile`: perfila **CSV** (filas, columnas, memoria, preview)
* `ts_forecast`: pronóstico **simple** de series temporales con fecha
* `report_generate`: genera **reportes HTML y PDF** (tablas + gráficos)
* `llm_chat`: chat con **Llama** vía **Ollama** (endpoint OpenAI-compatible)

Incluye un **cliente demo** (`demo.py`) que orquesta todo y un **chat CLI** (`cli.py`) con **contexto** de conversación. El servidor habla **JSON-RPC 2.0** por stdin/stdout (estilo MCP).

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

## 🦙 Modelo Llama con Ollama

1. **Instala/abre Ollama y arráncalo:**

```bash
ollama serve
```

2. **Descarga un modelo (ejemplo de 3B):**

```bash
ollama pull llama3.2:3b
```

## 🔧 Configuración

Crea un archivo `.env` (o copia de `.env.example`) con:

```env
OPENAI_API_BASE=http://localhost:11434/v1
OPENAI_API_KEY=ollama
LLM_MODEL=llama3.2:3b
LLM_SYSTEM_PROMPT_PATH=prompts/system_llm.txt
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=60
```

El **system prompt** principal está en `prompts/system_llm.txt` y es fácil de modificar.

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
* Genera un **reporte** en `reports/` (HTML o PDF, según config en `demo.py`)

### 2) Chat CLI con contexto

```bash
python cli.py
```

**Comandos útiles dentro del CLI:**

```bash
/tools               # lista herramientas MCP
/new                 # reinicia el contexto de chat
/save [archivo.md]   # guarda el transcript (por defecto reports/chat.md)
/call NAME {json}    # llama cualquier tool con JSON (ej: report_generate)
/help                # ayuda
/exit                # salir
```

**Ejemplo `/call`:**

```bash
/call report_generate {"title":"Demo","sections":["Hola"],"format":"pdf"}
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
│   │   ├── report_generate.py
│   │   └── ts_forecast.py
│   └── util/
│       ├── config.py        # (si aplica)
│       ├── io.py            # (si aplica)
│       └── registry.py
├── .env.example             # (opcional)
├── .gitignore
├── requirements.txt
├── main.py                  # servidor MCP (JSON-RPC)
├── demo.py                  # demo orquestada
└── cli.py                   # chatbot CLI con contexto
```

## 🔧 Troubleshooting

### **Ollama no responde / timeout**
* Asegúrate de tener `ollama serve` corriendo (verifica con `curl -s http://localhost:11434/api/version`).
* Verifica el modelo (`ollama list`) y el nombre en `LLM_MODEL`.

### **Falla exportación a PDF**
* Instala dependencias del sistema: 
  * **macOS:** `brew install pango cairo gdk-pixbuf libffi`
* Reinstala Python deps: `pip install weasyprint`

### **Permisos de archivos**
* Asegura que `reports/` exista y sea escribible (el código crea la carpeta si falta).

## 📄 Licencia

MIT — ver `LICENSE`.

## 👨‍💻 Créditos

**Proyecto académico:** MCP Server Local en Python (Parte 1)  
**Autor:** Jorge Luis Lopez 221038