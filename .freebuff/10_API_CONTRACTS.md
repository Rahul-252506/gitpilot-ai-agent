# API Contracts

## POST /api/analyses
Start an analysis.

Request:
```json
{
  "repository": "owner/repository",
  "issue_number": 42
}
```

Response:
```json
{
  "analysis_id": "string",
  "status": "queued|running|completed|failed"
}
```

## GET /api/analyses/{analysis_id}
Return current analysis state, execution events, and final result if available.

## POST /api/analyses/{analysis_id}/approve
Approve a pending write action.

## POST /api/analyses/{analysis_id}/reject
Reject a pending write action.

## GET /api/analyses
Return recent analyses with pagination.

## Health
`GET /api/health`

Response:
```json
{
  "status": "ok"
}
```

## API Rules
- Use Pydantic request/response models.
- Return consistent error shapes.
- Do not expose secrets.
- Validate repository and issue number.
- Use appropriate HTTP status codes.
- Keep long-running work out of a blocking request when practical.
