---
name: gcp-project-ops
description: Read-only Google Cloud operations diagnostics for project the49-487609. Use when Codex needs to inspect Cloud Run deployment status, backend logs, BigQuery datasets and safe query samples, Firestore documents, Cloud Storage receipt assets, Document AI processor/OCR behavior, Vertex AI model configuration, Firebase/Auth context, Redis/Memorystore status, or general GCP resource inventory with local gcloud CLI access.
---

# GCP Project Ops

## Defaults

Use project `the49-487609` and local `gcloud` CLI authentication. Treat all operations as read-only unless the user explicitly asks for a write/deploy action and approves it. Do not print, store, or request service account keys, Firebase private keys, `.env` secrets, access tokens, or credential JSON contents.

Start by confirming CLI context:

```bash
gcloud config get-value project
gcloud auth list
```

Prefer passing `--project the49-487609` instead of changing local gcloud defaults. If a command fails because APIs are disabled, permissions are missing, or credentials are absent, report the exact blocker and stop before suggesting mutations. A non-fatal warning about writing gcloud log files can be noted and ignored when command output still succeeds.

## Quick Inventory

For broad discovery, run the helper script:

```bash
python codex/gcp-project-ops/scripts/gcp_readonly_ops.py inventory
```

Use `--format json` when the result should be parsed by Codex. See `references/gcp-readonly-workflows.md` for exact command patterns and troubleshooting notes.

## Diagnostic Workflows

For Cloud Run, list services first, then describe the selected service and inspect recent revisions:

```bash
gcloud run services list --project the49-487609 --region asia-southeast1
gcloud run services describe SERVICE --project the49-487609 --region REGION
gcloud run revisions list --service SERVICE --project the49-487609 --region REGION
```

For backend logs, query Cloud Logging with a bounded time window and severity filter. Prefer `--limit` and `--freshness`; never stream indefinitely unless the user asks.

For BigQuery, list datasets and tables before querying. Use `bq query --nouse_legacy_sql --dry_run` for unfamiliar SQL, and add `LIMIT` to exploratory queries.

For Firestore, inspect database and collection metadata first. Read individual documents only when the collection path is known and relevant to the user's request.

For Document AI, verify processor IDs, locations, and enabled state before debugging OCR output. Correlate OCR failures with Cloud Run logs and GCS object metadata.

For Vertex AI, list models/endpoints by region and compare them with backend `.env` names such as `VERTEX_AI_MODEL`, `VERTEX_AI_INSIGHT_MODEL`, `VERTEX_AI_RECEIPT_MODEL`, and embedding model settings.

## Project Context

The local repository currently treats backend `.env` as sandbox configuration, not production. Prefer reading `backend/.env.example` for variable names and asking the user before relying on real `.env` values. Common services in this project include Cloud Run, Firebase Auth, Firestore, BigQuery, Cloud Storage, Document AI, Vertex AI/Gemini, and Redis/Memorystore.

## Escalation Rules

Read-only commands are acceptable when local credentials permit them. Before any create/update/delete/deploy/enable command, pause and ask for explicit user approval. This includes `gcloud run deploy`, `gcloud services enable`, IAM changes, Firestore writes, BigQuery table writes, bucket mutations, and Redis updates.
