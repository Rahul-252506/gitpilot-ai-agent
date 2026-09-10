# Implementation Plan

## Phase 1 — Project Setup
1. Create repository structure.
2. Initialize Next.js frontend.
3. Initialize FastAPI backend.
4. Add environment configuration.
5. Add `.gitignore`.
6. Add README.

## Phase 2 — Backend Foundation
1. FastAPI app.
2. Pydantic schemas.
3. Configuration module.
4. SQLite database.
5. Logging/error middleware.
6. Health endpoint.

## Phase 3 — GitHub Integration
1. GitHub service.
2. Issue retrieval.
3. Repository search.
4. File retrieval.
5. Related issue search.
6. Related PR search.
7. Unit tests with mocks.

## Phase 4 — Agent
1. Agent state/context.
2. Tool registry.
3. Tool-calling loop.
4. Step/time limits.
5. Prompt configuration.
6. Structured resolution schema.
7. Output validation.

## Phase 5 — API
1. Start analysis.
2. Analysis status.
3. Execution events.
4. Final report.
5. Approval/rejection endpoints.

## Phase 6 — Frontend
1. Input form.
2. Run state.
3. Agent timeline.
4. Resolution report.
5. Approval interface.
6. Error states.

## Phase 7 — Testing
1. Unit tests.
2. API tests.
3. Agent tests.
4. End-to-end happy path.
5. Failure-path testing.

## Phase 8 — Polish
1. README.
2. Architecture diagram.
3. `.env.example`.
4. Demo data/instructions.
5. Clean UI.
6. Git history with meaningful commits.

## Implementation Rules
- Build the smallest working version first.
- Do not add optional features before the MVP works.
- Keep frontend/backend boundaries clean.
- Keep provider-specific code behind an abstraction.
- Never expose secrets.
- Run tests after each major phase.
