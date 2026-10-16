# DocuMind AI

DocuMind AI is a public web application to query PDF documents using an AI agent. This repository contains the initial project structure (backend + frontend in a single deployable app).

## Requirements

- Python 3.11.9 (compatible with Python 3.11)

## Local setup (Windows)

1. Navigate to the repository

```powershell
cd C:\Users\USUARIO\Desktop\Proyectos\AgenteDeInteligenciaDocumental
```

2. Create and activate a virtual environment

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\activate
```

3. Install dependencies (editable + dev)

```powershell
pip install -e ".[dev]"
```

4. Configure environment variables (optional - defaults are fine)

```powershell
copy .env.example .env
```

5. Run the application

```powershell
uvicorn src.app.main:app --host 127.0.0.1 --port 8000 --reload
```

6. Test it

- UI: http://127.0.0.1:8000/
- Health check: http://127.0.0.1:8000/health

## Development

Run tests:

```powershell
pytest -q
```

Run linter:

```powershell
ruff check .
```

## Deployment (Render)

The app is prepared to run on Render. Use the following command:

```bash
uvicorn src.app.main:app --host 0.0.0.0 --port $PORT
```

The application reads `PORT` from environment variables (via settings).

## Notes

- The initial UI shows upload, question/answer area, and "Try with sample document" button as **pending features** (no real AI responses are generated yet).
- No LangGraph, embeddings, database, or LLM provider integrations are included in this initial structure.
