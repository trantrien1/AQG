# AIED-MCQ Frontend

Next.js frontend for the AIED-MCQ generation workflow. The FastAPI backend now lives in the parent `web` package, so both web layers are kept together under `API/web`.

## Run Locally

Start the backend from `API`:

```bash
python -m uvicorn web.app:app --host 127.0.0.1 --port 8080 --reload
```

Start the frontend from this directory:

```bash
npm run dev
```

By default the frontend calls `http://127.0.0.1:8080`. Override it with `NEXT_PUBLIC_API_URL` in `.env.local` when needed.

## Useful Commands

```bash
npm run lint
npm run build
```

## Layout

- `src/app` - Next.js routes and pages
- `src/components` - shared UI and domain components
- `src/lib/api.ts` - HTTP client matching the FastAPI contract
- `public` - static assets
