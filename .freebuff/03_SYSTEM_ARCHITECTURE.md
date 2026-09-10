# System Architecture

## High-Level Architecture

```text
Browser
  |
  v
Next.js / React Frontend
  |
  | REST API
  v
FastAPI Backend
  |
  +--> Agent Orchestrator
  |       |
  |       +--> LLM
  |       |
  |       +--> Tool Registry
  |               |
  |               +--> GitHub API
  |               +--> Repository Search
  |
  +--> SQLite
  |
  +--> Execution Logger
```

## Component Responsibilities

### Frontend
Collect inputs, start analyses, display agent progress, render the final report, and request approval for write actions.

### FastAPI Backend
Own validation, orchestration endpoints, LLM access, GitHub integration, persistence, and error translation.

### Agent Orchestrator
Maintains the agent loop, tool definitions, context, step limits, structured output, and termination conditions.

### Tool Layer
Expose narrowly scoped functions to the agent. Tools must validate arguments and return predictable results.

### GitHub Integration
Use GitHub APIs through a dedicated service module rather than calling GitHub directly from the UI.

### Database
SQLite stores analysis sessions, final reports, and bounded execution logs.

## Security Boundary
Secrets remain server-side. The browser never receives GitHub tokens or LLM provider secrets.

## Data Flow
1. User submits repository and issue.
2. Backend validates the request.
3. Agent receives a task and available tools.
4. Agent retrieves issue context.
5. Agent searches code and related GitHub items as needed.
6. Agent inspects relevant files.
7. Agent produces a validated resolution object.
8. Backend stores the result.
9. Frontend displays the report and timeline.
