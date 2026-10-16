# Project Instructions — AgenteDeInteligenciaDocumental

## Project goal
Build a production-minded document intelligence web application that allows users to upload PDFs, ask questions about their content, and receive evidence-grounded answers with source citations.

## Technology choices
- Python 3.11
- FastAPI and Pydantic for the REST API
- HTML, CSS and minimal JavaScript for the frontend
- LangGraph for the agent workflow when justified
- pytest for automated testing
- Ruff for linting
- GitHub Actions for CI
- Docker for reproducible deployment
- Render as the initial hosting platform

Keep the frontend and backend in one deployable application. Keep application logic in Python and separate modules by responsibility.

## Engineering principles
- Use type hints and small, focused functions.
- Validate all external inputs.
- Handle errors explicitly.
- Keep secrets in environment variables.
- Never commit .env files, API keys, tokens or private documents.
- Include tests for new functionality.
- Avoid unnecessary dependencies and premature complexity.
- Write the main README.md and all user-facing documentation in Spanish by default, unless another language is explicitly requested.
- Keep code, identifiers, endpoints and internal technical log messages in English.
- Prefer deterministic tests that do not require paid LLM API calls.
- Make external model providers configurable.

## Git workflow
- Never work directly on main.
- Use a separate branch for each issue or coherent task.
- Use descriptive Conventional Commit messages.
- Do not commit, push, merge or delete branches unless explicitly asked.
- Never rewrite Git history or discard existing changes without permission.
- Before changing files, inspect the existing repository and explain the plan.
- Keep changes focused on the current task.

## Quality requirements
- Every feature must include appropriate tests.
- CI must run linting and tests on pull requests.
- The application must provide a usable demo with a sample document.
- Answers must include supporting sources when available.
- The agent must handle insufficient evidence without fabricating information.
- Document known limitations and actual evaluation results.

## Working style
Work incrementally. Explain the purpose of each change, run the relevant checks, report actual results, and identify any remaining issues. Never claim that code or tests work without verifying them.