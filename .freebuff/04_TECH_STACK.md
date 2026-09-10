# Technology Stack

## Frontend
- Next.js
- React
- TypeScript
- Simple CSS or a lightweight component approach
- Fetch/standard HTTP client for backend calls

## Backend
- Python
- FastAPI
- Pydantic
- Uvicorn

## AI
- Provider-agnostic LLM service abstraction
- Function/tool calling
- Structured output validation

The first implementation should use one practical LLM provider selected by environment configuration. Do not hard-code a provider throughout the application.

## GitHub
- GitHub REST API
- Server-side authentication through environment variables

## Database
- SQLite
- SQLAlchemy or a small repository/data-access layer

## Testing
- pytest for backend
- Frontend tests only where they provide clear value

## Development
- Git
- GitHub
- `.env` for local secrets
- `.env.example` for documented configuration

## Design Rule
Prefer simple, stable dependencies. Do not add frameworks unless they solve a concrete project requirement.
