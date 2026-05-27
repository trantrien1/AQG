"""FastAPI backend cho web_new frontend.

Kiến trúc tối giản:
- State lưu trên filesystem ở `runs/<job_id>/`
- Một worker thread duy nhất per job (background task) cho generate
- Polling-based status (GET /job/:id/status đọc status.json)

Run:
    python -m uvicorn web.app:app --host 127.0.0.1 --port 8080 --reload
"""
