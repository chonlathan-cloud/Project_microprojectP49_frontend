# Repository Guidelines

## Project Structure & Module Organization

This repository is split into a FastAPI backend and a Next.js frontend. Backend source lives in `backend/app`, with routers under `backend/app/api/v1/endpoints`, models in `backend/app/models`, service integrations in `backend/app/services`, and configuration in `backend/app/core`. Backend tests live in `backend/tests`.

Frontend code lives in `frontend/src`. App Router pages are in `frontend/src/app`, reusable UI is in `frontend/src/components`, shared utilities are in `frontend/src/lib`, and TypeScript types are in `frontend/src/types`. Design docs are in `Document/`. Sample receipts and POS files support testing.

## Build, Test, and Development Commands

- `cd frontend && npm install`: install frontend dependencies from `package-lock.json`.
- `cd frontend && npm run dev`: start the Next.js dev server.
- `cd frontend && npm run build`: build the production frontend.
- `cd frontend && npm run lint`: run the Next.js ESLint configuration.
- `cd backend && python3 -m venv venv && source venv/bin/activate`: create and enter a Python virtual environment.
- `cd backend && pip install -r requirements.txt`: install backend dependencies.
- `cd backend && uvicorn app.main:app --reload`: run the FastAPI API locally.
- `cd backend && PYTHONPATH=. python tests/test_receipts.py`: run mocked receipt API tests.
- `cd backend && TEST_BRANCH_ID=branch_001 PYTHONPATH=. python tests/test_real_scenario.py`: run the real cloud-backed receipt scenario after configuring `.env`.

## Coding Style & Naming Conventions

Use 4-space indentation for Python and 2-space indentation for TypeScript/TSX. Keep FastAPI endpoints grouped by resource in `endpoints/*.py`, and put external-service logic in `services/*.py`. Frontend feature components use PascalCase filenames; shared UI primitives use lowercase names, matching `components/ui/button.tsx`. Prefer the `@/` alias for frontend imports.

## Testing Guidelines

Backend tests are script-style FastAPI `TestClient` tests named `test_*.py`. Mock cloud services for local coverage in `test_receipts.py`; reserve `test_real_scenario.py` for credentialed integration checks. The frontend has lint/build validation but no dedicated test runner, so validate UI changes with `npm run lint` and `npm run build`.

## Commit & Pull Request Guidelines

Recent commits use short summaries such as `add NoSQL` and `cache branches...`. Keep commits focused and use concise imperative messages. Pull requests should describe behavior changes, list test commands, link related issues or docs, and include screenshots for visible frontend updates.

## Security & Configuration Tips

Create backend secrets from `backend/.env.example`; do not commit `.env`, Firebase Admin SDK JSON files, or cloud credentials. Keep deployment changes in `deploy_Backend.sh` and `deploy_Frontend.sh` explicit and documented in the PR.
