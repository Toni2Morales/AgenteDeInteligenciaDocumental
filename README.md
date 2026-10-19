# DocuMind AI

DocuMind AI es una aplicación web pública para consultar documentos PDF mediante un agente de IA.
Este repositorio contiene el backend y el frontend en una única aplicación desplegable. Incluye la
**ingesta y extracción de texto de PDFs** y la **infraestructura local de IA**: persistencia en
PostgreSQL con pgvector y generación de embeddings con Ollama.

## Requisitos

- Python 3.11.9 (compatible con Python 3.11)

Para la **infraestructura local de IA** (PostgreSQL con pgvector y Ollama) se necesita además:

- [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) (Windows 11).
- [Ollama](https://ollama.com/download) para ejecutar los modelos en local.

Ambos son **opcionales para la ingesta de PDF**: solo son necesarios para la
persistencia vectorial y los embeddings descritos más abajo.

## Puesta en marcha local (Windows)

1. Sitúate en el repositorio

```powershell
cd C:\Users\USUARIO\Desktop\Proyectos\AgenteDeInteligenciaDocumental
```

2. Crea y activa un entorno virtual

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\activate
```

3. Instala las dependencias (modo editable + dependencias de desarrollo)

```powershell
pip install -e ".[dev]"
```

4. Configura las variables de entorno (opcional, los valores por defecto son válidos)

```powershell
copy .env.example .env
```

5. Arranca la aplicación

```powershell
uvicorn src.app.main:app --host 127.0.0.1 --port 8000 --reload
```

6. Pruébala

- Interfaz web: http://127.0.0.1:8000/
- Comprobación de estado (*health check*): http://127.0.0.1:8000/health
- Documentación interactiva de la API (Swagger UI): http://127.0.0.1:8000/docs

## Variables de entorno

| Variable | Descripción | Valor por defecto |
| --- | --- | --- |
| `APP_NAME` | Nombre visible de la aplicación | `DocuMind AI` |
| `ENV` | Entorno de ejecución | `dev` |
| `HOST` | Host de escucha | `127.0.0.1` |
| `PORT` | Puerto de escucha | `8000` |
| `MAX_UPLOAD_SIZE_MB` | Tamaño máximo permitido para un PDF subido, en MB | `10` |
| `POSTGRES_USER` | Usuario de PostgreSQL (también lo usa Docker Compose) | `documind` |
| `POSTGRES_PASSWORD` | Contraseña de PostgreSQL (valor de desarrollo local) | `documind` |
| `POSTGRES_DB` | Nombre de la base de datos | `documind` |
| `POSTGRES_HOST` | Host de PostgreSQL | `localhost` |
| `POSTGRES_PORT` | Puerto de PostgreSQL | `5432` |
| `POSTGRES_CONNECT_TIMEOUT` | Timeout de conexión a PostgreSQL, en segundos | `5` |
| `DATABASE_URL` | Cadena de conexión completa; si está vacía se construye con las variables `POSTGRES_*` | (vacío) |
| `OLLAMA_BASE_URL` | URL del servidor Ollama local | `http://localhost:11434` |
| `OLLAMA_LLM_MODEL` | Modelo de lenguaje | `qwen2.5:3b` |
| `OLLAMA_EMBEDDING_MODEL` | Modelo de embeddings | `embeddinggemma` |
| `OLLAMA_TIMEOUT_SECONDS` | Timeout de las llamadas a Ollama, en segundos | `120` |
| `EMBEDDING_DIMENSION` | Dimensión real de los embeddings. **Debe verificarse** antes de migrar | (vacío) |
| `EMBEDDING_VERSION` | Etiqueta de versión guardada junto a cada embedding | `1` |

> `POSTGRES_PASSWORD=documind` es un valor de desarrollo local, no una credencial real.
> Nunca subas tu archivo `.env` al repositorio.

## Infraestructura local de IA (PostgreSQL + pgvector + Ollama)

Esta parte permite ejecutar todo el sistema **en local**, sin APIs de pago ni claves de
proveedores. Todavía **no** incluye la cadena de preguntas y respuestas: solo prepara los cimientos
(almacenamiento de documentos y fragmentos con embeddings, y generación de embeddings).

### Arquitectura local

```
┌──────────────┐   HTTP    ┌───────────────┐   SQL    ┌────────────────────────┐
│  FastAPI     │──────────▶│    Ollama     │          │  PostgreSQL + pgvector │
│  (src/app)   │           │  :11434       │          │  (contenedor Docker)   │
│              │─────────────────────────────────────▶│  :5432 (solo localhost)│
└──────────────┘           └───────────────┘          └────────────────────────┘
      │                                                          ▲
      │  scripts/migrate.py (migraciones .sql versionadas)       │
      └──────────────────────────────────────────────────────────┘
```

- **Ollama** genera embeddings (`embeddinggemma`) y, en el futuro, respuestas (`qwen2.5:3b`).
- **PostgreSQL + pgvector** guarda documentos y fragmentos con sus vectores.
- Los **PDF originales no se persisten**: solo se guardan metadatos y el texto extraído.

### 1. Iniciar PostgreSQL

```powershell
copy .env.example .env
docker compose up -d
docker compose ps            # el estado debe ser "healthy"
```

El contenedor usa la imagen `pgvector/pgvector:pg16`, guarda los datos en un volumen con nombre
(`documind_pgdata`) y publica el puerto **solo en `127.0.0.1`**.

Detener y eliminar:

```powershell
docker compose stop          # detiene sin borrar datos
docker compose down          # elimina el contenedor, conserva el volumen
docker compose down -v       # elimina también los datos (reconstrucción desde cero)
```

> Si `docker` no está en el `PATH`, usa la ruta completa, por ejemplo:
> `& "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe" compose up -d`.

### 2. Verificar Ollama y la dimensión de los embeddings

```powershell
python scripts/verify_ollama.py
```

El script comprueba que Ollama responde, que los modelos están descargados y **mide la dimensión
real** del modelo de embeddings. Copia el valor en `EMBEDDING_DIMENSION` de tu `.env`.

Los modelos **no se descargan automáticamente**; hay que hacerlo a mano cuando estés preparado:

```powershell
ollama pull embeddinggemma     # https://ollama.com/library/embeddinggemma
ollama pull qwen2.5:3b         # https://ollama.com/library/qwen2.5
```

Revisa las **licencias y condiciones de uso** de cada modelo en sus páginas oficiales antes de
usarlos.

### 3. Crear el esquema (migraciones)

```powershell
python scripts/migrate.py
```

- Las migraciones son archivos `.sql` versionados en `migrations/`, aplicados una sola vez y
  registrados con su *checksum* en la tabla `schema_migrations`.
- La columna vectorial se declara como `vector({{embedding_dim}})`, donde la dimensión proviene de
  `EMBEDDING_DIMENSION`. **El runner se niega a migrar si esa variable no está definida**, de modo
  que nunca se crea el esquema con una dimensión inventada.

#### Reconstruir la base de datos desde cero

```powershell
docker compose down -v       # borra el volumen de datos
docker compose up -d         # contenedor nuevo y vacío
python scripts/migrate.py    # vuelve a crear el esquema
```

#### Cambiar de modelo o de dimensión (reindexado)

Los vectores de modelos distintos **nunca se comparan**: cada fragmento guarda su
`embedding_model`, `embedding_dim` y `embedding_version`, y las consultas filtran por modelo y
dimensión. Si cambias de modelo o de dimensión:

1. Verifica la nueva dimensión con `python scripts/verify_ollama.py` y actualiza
   `OLLAMA_EMBEDDING_MODEL` y `EMBEDDING_DIMENSION`.
2. Crea una migración nueva que ajuste la columna `embedding` a la nueva dimensión.
3. **Regenera** los embeddings de todos los fragmentos con el nuevo modelo antes de consultar.

Mientras no se regeneren, los vectores antiguos quedan aislados por el filtro de modelo/dimensión.

### 4. Comprobar la conexión con Ollama

```powershell
curl.exe http://localhost:11434/api/version
curl.exe http://localhost:11434/api/tags
```


## Ingesta de PDF: API

La aplicación expone un endpoint que recibe un archivo PDF, valida el archivo y extrae su texto
página por página. El archivo se procesa **en memoria** y **nunca se guarda en disco**.

### `POST /api/documents/upload`

- **Cuerpo de la petición:** `multipart/form-data` con el campo `file` (el PDF).
- **Respuesta correcta (`200`):** un JSON tipado con el nombre del documento, el número de páginas y
  el texto extraído por página.

```json
{
  "document_name": "informe.pdf",
  "page_count": 2,
  "pages": [
    { "page_number": 1, "text": "Texto de la primera página..." },
    { "page_number": 2, "text": "Texto de la segunda página..." }
  ]
}
```

### Validaciones y códigos de error

| Situación | Código HTTP |
| --- | --- |
| El archivo no es un PDF | `400 Bad Request` |
| El archivo está vacío | `400 Bad Request` |
| El PDF está corrupto, mal formado o cifrado | `400 Bad Request` |
| El archivo supera `MAX_UPLOAD_SIZE_MB` | `413 Content Too Large` |
| El PDF no contiene texto extraíble | `422 Unprocessable Content` |
| Error inesperado durante la extracción | `422 Unprocessable Content` |
| Falta el campo `file` | `422 Unprocessable Content` |

### Ejemplo de uso

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/documents/upload" -F "file=@C:\ruta\a\informe.pdf"
```

También puedes probarlo desde la documentación interactiva en http://127.0.0.1:8000/docs.

## Demostración y evaluación

El directorio [`demo/`](demo/) contiene un documento de ejemplo reproducible y un conjunto de
preguntas de evaluación para comprobar más adelante la recuperación de información y las citas:

- `demo/document.txt` — fuente de texto del documento (contenido original y propio sobre el Sistema
  Solar, con datos públicos y estables).
- `demo/document.pdf` — PDF de demostración (4 páginas), generado de forma determinista.
- `demo/evaluation.json` — 8 preguntas con respuesta esperada, página y sección de origen.
- `demo/README.md` — guía detallada en español.

Regenerar el PDF a partir de la fuente:

```powershell
python scripts/generate_demo_pdf.py
```

Subir el documento de demostración al endpoint de ingesta:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/documents/upload" -F "file=@demo\document.pdf"
```

## Desarrollo

Ejecutar las pruebas (unitarias; las de integración se omiten por defecto):

```powershell
pytest -q
```

Ejecutar las pruebas de integración contra PostgreSQL (requiere el contenedor en marcha y el
esquema migrado):

```powershell
$env:RUN_DB_TESTS = "1"; pytest tests/integration -q
```

Ejecutar la prueba de integración opcional contra Ollama real (requiere un Ollama funcional y los
modelos descargados):

```powershell
$env:RUN_OLLAMA_TESTS = "1"; pytest tests/integration -q
```

Comprobar el formato y el linter:

```powershell
ruff format --check .
ruff check .
```

## Despliegue (Render)

La aplicación está preparada para ejecutarse en Render. Usa el siguiente comando:

```bash
uvicorn src.app.main:app --host 0.0.0.0 --port $PORT
```

La aplicación lee el puerto desde la variable de entorno `PORT` (a través de la configuración).

## Arquitectura

- `src/app/api/` — routers de FastAPI (`health`, `documents`).
- `src/app/services/` — lógica de negocio independiente del HTTP: `pdf_ingestion`, `ollama` y
  `embeddings`.
- `src/app/db/` — acceso a datos: `connection`, `migrations` (runner versionado) y `repositories`
  (documentos, fragmentos y búsqueda por similitud).
- `src/app/schemas/` — modelos Pydantic del API y dataclasses internas (`chunk`).
- `src/app/config/` — configuración de la aplicación (`settings`).
- `src/app/templates/` y `src/app/static/` — interfaz web (HTML, CSS y JavaScript).
- `migrations/` — migraciones SQL versionadas.
- `compose.yaml` — PostgreSQL + pgvector para desarrollo local.
- `demo/` — documento de demostración y conjunto de preguntas de evaluación.
- `scripts/` — utilidades de desarrollo (`generate_demo_pdf`, `migrate`, `verify_ollama`).

## Problemas frecuentes

- **`docker` no se reconoce como comando.** Docker Desktop no añadió su CLI al `PATH`. Usa la ruta
  completa: `& "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe" compose up -d`.
- **`error getting credentials ... docker-credential-desktop`.** Añade temporalmente el directorio
  `...\DockerDesktop\resources\bin` al `PATH` antes de ejecutar `docker`.
- **La conexión a PostgreSQL se queda colgada con `localhost`.** Ocurre por la resolución de
  direcciones en algunos equipos; el proyecto aplica `POSTGRES_CONNECT_TIMEOUT` (por defecto 5 s).
  Si aun así falla, usa `POSTGRES_HOST=127.0.0.1` o un `DATABASE_URL` explícito.
- **Ollama responde pero falla al ejecutar un modelo** (`llama-server binary not found`). La
  instalación de Ollama está incompleta: reinstálala desde la página oficial. `verify_ollama.py`
  avisará y, como respaldo, leerá la dimensión de los metadatos GGUF del modelo ya descargado.
- **`EMBEDDING_DIMENSION` vacío.** Es intencional: ejecuta `python scripts/verify_ollama.py` y
  copia el valor antes de migrar.

## Limitaciones de rendimiento

- Equipos con gráficos integrados ejecutan los modelos en **CPU**; `qwen2.5:3b` es pequeño
  precisamente para eso, pero la generación será lenta.
- Evita tener cargados a la vez el modelo de lenguaje y el de embeddings si la memoria es justa
  (Ollama los descarga por inactividad con `OLLAMA_KEEP_ALIVE`).
- La búsqueda por similitud usa un índice **HNSW** con distancia coseno, adecuado para colecciones
  pequeñas y medianas; para volúmenes muy grandes habría que revisar el índice y los recursos.

## Notas y limitaciones

- Está implementada la **ingesta y extracción de texto de PDFs**, además de la **base de
  persistencia y los servicios de embeddings**. La interfaz muestra las áreas de subida,
  pregunta/respuesta y documento de ejemplo como funciones **pendientes**.
- El documento y las preguntas de `demo/` sirven para **preparar y evaluar** el futuro sistema RAG;
  todavía no hay generación de respuestas.
- Todavía **no** hay cadena de preguntas y respuestas, ni LangGraph que la orqueste.
- Los PDFs subidos **no se persisten**: se procesan en memoria y se descartan. La base de datos
  guarda solo metadatos del documento y el texto de sus fragmentos.
- `OllamaClient.generate()` existe como preparación, pero **no está conectado a ningún endpoint**.
- Ningún contenido del documento se ejecuta: el texto se extrae con `pypdf` y no se interpreta.
