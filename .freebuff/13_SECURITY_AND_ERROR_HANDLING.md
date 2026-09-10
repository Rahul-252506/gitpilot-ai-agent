# Security and Error Handling

## Secrets
Required secrets must come from environment variables.

Never commit:
- API keys
- GitHub tokens
- passwords
- `.env`

Provide `.env.example` with placeholder names only.

## GitHub Security
- Use minimum required token permissions.
- Keep GitHub authentication server-side.
- Do not let the model construct arbitrary authenticated requests.
- Restrict write tools and require approval.

## Input Validation
Validate:
- repository owner/repo format
- issue number
- tool arguments
- output sizes

## Errors
Handle:
- invalid repository
- issue not found
- GitHub rate limits
- authentication failures
- network timeout
- LLM failure
- malformed tool output
- structured-output validation failure
- execution timeout

## Logging
Logs should contain:
- analysis ID
- event type
- tool name
- status
- duration where useful
- concise error summary

Never log:
- access tokens
- API keys
- full authorization headers
- sensitive user secrets

## Recovery
Non-critical tool failures should be recorded and may allow continuation. Critical failures should end the analysis cleanly.
