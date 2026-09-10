# Backend Design

## Suggested Structure

```text
backend/
├── app/
│   ├── main.py
│   ├── api/
│   ├── agent/
│   ├── services/
│   ├── tools/
│   ├── models/
│   ├── schemas/
│   ├── db/
│   └── core/
└── tests/
```

## Responsibilities

### API Layer
Expose HTTP endpoints and translate service results into response schemas.

### Agent Layer
Implement the tool-calling loop and final structured output.

### Services
- GitHub service
- LLM service
- Analysis service
- Persistence service

### Tools
Each tool has:
- Name
- Description
- Typed input
- Typed output
- Timeout
- Error handling

### Schemas
Use Pydantic models for API requests, tool results, and final resolution reports.

## Agent Safety Limits
- Maximum number of tool calls per analysis
- Maximum execution duration
- Maximum tool output size
- No unrestricted shell execution
- No arbitrary filesystem access

## Configuration
Load configuration from environment variables and fail clearly when required values are missing.
