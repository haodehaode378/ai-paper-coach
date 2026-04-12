# AI Paper Coach

AI Paper Coach is a student-oriented paper reading agent.
Input a paper URL or upload a PDF, and get:
- 3-minute summary
- explain-to-classmate version
- reproduction guide

The MVP uses collaborative mode:
Qwen draft -> MiniMax review -> Qwen patch.

## Project Layout
- `apps/web`: Vue 3 + Vite frontend
- `services/api`: FastAPI backend
- `PROJECT_PLAYBOOK.md`: workflow and prompt strategy
- `run.py`: starts both the API and the Vue dev server

## Quick Start
1. Install backend dependencies:
```bash
cd services/api
pip install -r requirements.txt
```

2. Install frontend dependencies:
```bash
cd apps/web
npm install
```

3. Configure env:
- copy `.env.example` to `.env`
- fill Qwen and MiniMax API settings (optional for MVP fallback)

4. Start both services:
```bash
python run.py
```

You can also start them manually:
```bash
cd services/api
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

```bash
cd apps/web
npm run dev -- --host 127.0.0.1 --port 5500
```

## API Endpoints
- `POST /ingest`
- `POST /analyze`
- `POST /review`
- `POST /finalize`
- `GET /report/{paper_id}`
- `GET /export/{paper_id}.md`
- `GET /trace/{paper_id}`
- `POST /validate-models`

## Notes
- Frontend is now a Vue single-page app, with task and result pages handled by Vue Router.
- If model API keys are not configured, backend falls back to heuristic draft/review/patch mode.
- URL parsing is best for direct PDF links; arXiv `abs` links currently return summary-only fallback if PDF is unavailable.
