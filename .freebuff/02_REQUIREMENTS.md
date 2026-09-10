# Requirements

## Functional Requirements

### FR1 — Repository Input
The user can provide a GitHub repository in `owner/repository` form.

### FR2 — Issue Input
The user can provide a GitHub issue number.

### FR3 — Issue Retrieval
The backend can retrieve issue title, body, labels, author, state, comments, and metadata.

### FR4 — Repository Search
The agent can search repository files for keywords related to the issue.

### FR5 — File Inspection
The agent can retrieve relevant source files with bounded content.

### FR6 — Related Issue Search
The agent can search related GitHub issues and pull requests.

### FR7 — Agent Orchestration
The agent can select and call tools over multiple steps.

### FR8 — Structured Resolution
The final result follows a validated structured schema.

### FR9 — Execution Logs
The UI displays tool calls and execution status.

### FR10 — Error Handling
Tool/API/LLM failures are handled without crashing the application.

### FR11 — Approval
Any GitHub write operation requires explicit user approval.

### FR12 — History
Completed analyses can be stored locally for later viewing.

## Non-Functional Requirements
- API keys must be stored in environment variables.
- GitHub tokens must never appear in frontend code or logs.
- Backend endpoints should validate input.
- Tool outputs must have bounded sizes.
- UI should show loading and failure states.
- Code should be modular and testable.
- README and setup instructions must be maintained.

## MVP Acceptance Criteria
A user can enter a repository and issue number, start an analysis, watch the agent execute multiple tools, and receive a structured resolution report.
