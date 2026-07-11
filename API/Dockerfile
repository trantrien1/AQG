FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pipeline/ pipeline/
COPY web/__init__.py web/app.py web/auth.py web/bank_exports.py web/bank_store.py web/db.py web/jobs.py web/store.py web/
COPY run.py .

# runs/ (job artifacts) và data/ (question bank) nên mount volume để giữ dữ liệu
RUN mkdir -p runs data output

EXPOSE 8080

CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8080"]
