# Testing and Validation

## Backend Unit Tests
Test:
- repository input validation
- issue number validation
- GitHub service error handling
- tool argument validation
- tool output truncation
- agent termination limits
- structured report validation
- database persistence

## API Tests
Test:
- start analysis
- get analysis
- health endpoint
- invalid requests
- failed analysis
- approval/rejection

## Agent Tests
Use mocked tools and deterministic fixtures.

Test scenarios:
1. Normal issue investigation
2. Issue not found
3. Repository search returns no results
4. GitHub rate limit
5. Tool failure followed by recovery
6. LLM structured output validation failure
7. Step limit reached
8. Proposed write action requiring approval

## Frontend Validation
Check:
- form validation
- loading state
- timeline rendering
- final report rendering
- error display
- approval flow

## Definition of Done
The MVP is complete only when a clean local setup can perform an end-to-end analysis with mocked or configured external services and tests pass.
