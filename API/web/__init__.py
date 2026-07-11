"""FastAPI backend for the bundled Next.js frontend.

Minimal architecture:
- State is stored on the filesystem at `runs/<job_id>/`
- One background worker per job handles generation
- Polling-based status via `GET /job/:id/status`

Run backend:
    python -m uvicorn web.app:app --host 127.0.0.1 --port 8080 --reload

Run frontend:
    cd web/frontend
    npm run dev
"""
