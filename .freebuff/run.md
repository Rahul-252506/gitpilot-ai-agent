# GitPilot — Live Preview Run Doc

Reproduce the uncommitted artifacts a fresh worktree needs, then run the two dev
servers. This workspace is the primary checkout, so most artifacts already exist;
a fresh worktree should follow the "copy from main checkout" steps below.

## 1. Reproduce required artifacts

### Backend environment (required)

- `backend/.env` is git-ignored and NOT in the repo. In a fresh worktree, copy it
  from the main checkout (never commit it):
  ```
  Copy-Item ..\main_checkout\backend\.env backend\.env
  ```
  It must define (values only in your local `.env`, never in the README/repo):
  - `GITHUB_TOKEN` — server-side GitHub token
  - `LLM_PROVIDER=gemini` — or `openai` / `mock`
  - `GEMINI_API_KEY` — only needed when `LLM_PROVIDER=gemini`

### Backend dependencies

```
cd backend
pip install -r requirements.txt
pip install -r requirements-dev.txt   # adds pytest
```

### Frontend dependencies

```
cd frontend
npm install
```

- No `frontend/.env.local` is required: `NEXT_PUBLIC_API_BASE_URL` defaults to
  `http://localhost:8000`.

## 2. Run the servers

### Backend (port 8000)

From `backend/`:
```
python -m uvicorn app.main:app --port 8000
```
Health: `curl http://localhost:8000/api/health` → `{"status":"ok"}`.

### Frontend (port 3000)

From `frontend/`:
```
node node_modules/next/dist/bin/next dev --port 3000
```
(or `npm run dev` — it invokes the same Next.js binary via `node`.)

Open http://localhost:3000.

### Detached (survives the conversation) — Windows

The `Start-Process` detach recipe below keeps both servers alive after the tool
session ends. Note the bash tool's call may report a timeout even though the
process starts and survives — verify separately with `netstat`/`Get-Process`.

Backend:
```powershell
(Start-Process -FilePath 'python.exe' -ArgumentList '-m','uvicorn','app.main:app','--port','8000' -WorkingDirectory 'D:\InnovationHacks\Week3\backend' -RedirectStandardOutput 'D:\InnovationHacks\Week3\.freebuff\backend-preview.log' -RedirectStandardError 'D:\InnovationHacks\Week3\.freebuff\backend-preview.err' -WindowStyle Hidden -PassThru).Id
```

Frontend:
```powershell
(Start-Process -FilePath 'node.exe' -ArgumentList 'node_modules/next/dist/bin/next','dev','--port','3000' -WorkingDirectory 'D:\InnovationHacks\Week3\frontend' -RedirectStandardOutput 'D:\InnovationHacks\Week3\.freebuff\preview-4ddd81ec-2384-493e-9d6e-083f47b2a3a1.log' -RedirectStandardError 'D:\InnovationHacks\Week3\.freebuff\preview-4ddd81ec-2384-493e-9d6e-083f47b2a3a1.log.err' -WindowStyle Hidden -PassThru).Id
```

Verify:
```
netstat -ano | grep -E ":8000|:3000" | grep LISTEN
powershell -NoProfile -Command "Get-Process -Id <pid>"
```

### Register the preview

Register `http://127.0.0.1:3000` with the frontend process id (the LISTENING pid
on port 3000).
