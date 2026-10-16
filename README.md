# DocuMind AI

DocuMind AI es una aplicación web pública para consultar documentos PDF mediante un agente de IA.
Este repositorio contiene la estructura inicial del proyecto (backend + frontend en una única
aplicación desplegable) y, de momento, la funcionalidad de **ingesta y extracción de texto de PDFs**.

## Requisitos

- Python 3.11.9 (compatible con Python 3.11)

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

## Desarrollo

Ejecutar las pruebas:

```powershell
pytest -q
```

Ejecutar el linter:

```powershell
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
- `src/app/services/` — lógica de negocio (`pdf_ingestion`), independiente del HTTP.
- `src/app/schemas/` — modelos Pydantic que describen las estructuras de datos.
- `src/app/config/` — configuración de la aplicación (`settings`).
- `src/app/templates/` y `src/app/static/` — interfaz web (HTML, CSS y JavaScript).

## Notas y limitaciones

- Actualmente solo está implementada la **ingesta y extracción de texto de PDFs**. La interfaz muestra
  las áreas de subida, pregunta/respuesta y documento de ejemplo como funciones **pendientes**.
- Todavía **no** hay embeddings, base de datos, LangGraph ni integraciones con proveedores de LLM.
- Los archivos subidos no se persisten; se procesan en memoria y se descartan.
- Ningún contenido del documento se ejecuta: el texto se extrae con `pypdf` y no se interpreta.
