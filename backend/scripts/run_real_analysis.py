"""One real end-to-end GitPilot analysis per model — live GitHub + live Gemini.

Diagnostic companion to gemini_compat_probe.py: drives the REAL
AnalysisService (agent loop, real tool executions against the real GitHub
repository) exactly as production does, printing each timeline event as it
is recorded. No production files are modified; the model can be overridden
on the command line via the constructor (never via config files).

Usage (from backend/):
    python scripts/run_real_analysis.py [model ...]
"""
from __future__ import annotations

import os
import sys
import time

backend_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

REPO = "Rahul-252506/gitpilot-demo"
ISSUE = 1


def main() -> int:
    from app.core.config import Settings
    from app.db.database import create_engine_for, init_db, make_session_factory
    from app.services.analysis_service import AnalysisService
    from app.services.github_service import GitHubService
    from app.services.llm.gemini_provider import GeminiLLMProvider

    base = Settings()  # loads backend/.env; provider=gemini, keys set
    models = sys.argv[1:] or [base.gemini_model]
    overall_ok = True

    for model in models:
        print(f"\n{'=' * 72}\nREAL ANALYSIS — {base.repository if hasattr(base, 'repository') else REPO} #{ISSUE} — model={model}\n{'=' * 72}")
        settings = Settings()
        settings.gemini_model = model  # runtime override only
        engine = create_engine_for(settings.database_path)
        init_db(engine)
        session_factory = make_session_factory(engine)
        github = GitHubService(token=settings.github_token)
        provider = GeminiLLMProvider(api_key=settings.gemini_api_key, model=model)
        service = AnalysisService(session_factory, github, provider, settings)

        started = time.time()
        analysis_id = service.start_analysis(REPO, ISSUE)
        print(f"  analysis_id: {analysis_id}")
        # The API route launches execution via FastAPI BackgroundTasks; the
        # runner replicates that wiring here.
        import threading

        threading.Thread(target=service.run_analysis, args=(analysis_id,), daemon=True).start()
        seen = 0
        last_error = None
        while True:
            detail = service.get_analysis(analysis_id)  # Pydantic response model
            events = detail.events or []
            for ev in events[seen:]:
                prefix = f"[{ev.tool_name}] " if ev.tool_name else ""
                print(f"  {ev.event_type:<18} {prefix}{ev.summary[:110]}")
            seen = len(events)
            if detail.status not in ("queued", "running", "waiting_approval"):
                last_error = detail.error_message
                break
            if time.time() - started > 420:
                print("  !!! local wait timeout")
                break
            time.sleep(3)

        elapsed = time.time() - started
        status = detail.status
        print(f"\n  final status: {status}  ({elapsed:.0f}s, {seen} events)")
        if last_error:
            print(f"  error: {last_error[:300]}")
        report = detail.report
        if report:
            print(f"  report: summary={report.issue_summary[:120]!r}")
            print(f"          category={report.category} priority={report.priority} confidence={report.confidence}")
            print(f"          affected_files={report.affected_files}")
            print(f"          evidence={len(report.evidence)} item(s), warnings={len(report.warnings)}")
        print(f"  model {model}: {'SUCCESS' if status == 'completed' else 'FAILED'}")
        if status != "completed":
            overall_ok = False
        time.sleep(5)  # be gentle with free-tier RPM between runs

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
