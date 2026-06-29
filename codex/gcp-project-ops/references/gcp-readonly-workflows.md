# GCP Read-Only Workflows

Use project `the49-487609` unless the user overrides it. The default region for this project is `asia-southeast1`; verify region when a resource is not found.

## Baseline Checks

```bash
gcloud config get-value project
gcloud auth list
gcloud services list --enabled --project the49-487609
```

If the active project differs, prefer passing `--project the49-487609` on commands. Run `gcloud config set project the49-487609` only after telling the user because it changes local CLI state. Never enable APIs, change IAM, deploy services, or modify data without explicit approval.

If `gcloud` prints a non-fatal warning about writing log files under `~/.config/gcloud/logs` but still returns command output, treat it as a local sandbox permission issue rather than a cloud failure.

## Cloud Run

List and inspect services:

```bash
gcloud run services list --project the49-487609 --region asia-southeast1
gcloud run services describe SERVICE --project the49-487609 --region REGION
gcloud run revisions list --service SERVICE --project the49-487609 --region REGION
```

Check fields for URL, latest ready revision, traffic split, service account, environment variables, image, CPU/memory, min/max instances, and last deployment time.

## Backend Logs

Use bounded reads:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="SERVICE" AND severity>=ERROR' \
  --project the49-487609 --freshness 2h --limit 100
```

For receipt/OCR debugging, search logs around the upload time and include request IDs, receipt IDs, branch IDs, processor IDs, and model names when visible. Do not expose tokens or secrets if logs contain them.

## BigQuery

Discover before querying:

```bash
bq ls --project_id the49-487609
bq ls the49-487609:DATASET
bq show --schema --format=prettyjson the49-487609:DATASET.TABLE
```

Use Standard SQL with `LIMIT` for exploration:

```bash
bq query --nouse_legacy_sql --dry_run 'SELECT * FROM `the49-487609.DATASET.TABLE` LIMIT 20'
bq query --nouse_legacy_sql --max_rows=20 'SELECT * FROM `the49-487609.DATASET.TABLE` LIMIT 20'
```

Prefer dry runs for unfamiliar queries. Avoid DDL, DML, export, load, and scheduled-query changes unless explicitly approved.

## Firestore

Start with database metadata:

```bash
gcloud firestore databases list --project the49-487609
gcloud firestore databases describe --database "(default)" --project the49-487609
```

For document reads, use the helper script because `gcloud` has limited document inspection support:

```bash
python codex/gcp-project-ops/scripts/gcp_readonly_ops.py firestore --path COLLECTION --limit 20
python codex/gcp-project-ops/scripts/gcp_readonly_ops.py firestore --path COLLECTION/DOCUMENT --document
```

Read only the minimum document paths needed for the user's question.

## Document AI / Receipt OCR

List processors and inspect the configured receipt processor:

```bash
gcloud documentai processors list --project the49-487609 --location asia-southeast1
gcloud documentai processors describe PROCESSOR_ID --project the49-487609 --location LOCATION
```

Verify processor state, type, location, and display name against backend config. When OCR quality is poor, correlate Cloud Run logs, GCS object metadata, image size/preprocessing settings, and the backend variables `RECEIPT_EXTRACTION_MODE`, `VISION_PREPROCESS_ENABLED`, and `OCR_PREPROCESS_ENABLED`.

## Vertex AI / Gemini

List regional models and endpoints:

```bash
gcloud ai models list --project the49-487609 --region asia-southeast1
gcloud ai endpoints list --project the49-487609 --region asia-southeast1
```

Compare configured names with backend variables such as `VERTEX_AI_MODEL`, `VERTEX_AI_INSIGHT_MODEL`, `VERTEX_AI_RECEIPT_MODEL`, `VERTEX_AI_EMBEDDING_MODEL`, `GCP_LOCATION`, and `VERTEX_AI_LOCATION`. For Gemini model names that do not appear as deployed endpoints, check whether the backend uses publisher models through Vertex AI.

## Cloud Storage

```bash
gcloud storage buckets list --project the49-487609
gcloud storage ls gs://BUCKET --project the49-487609
```

For receipt issues, confirm bucket existence, object paths, content type, size, and timestamps. Do not download or print receipt contents unless necessary.

## Firebase Auth

Firebase Auth is usually inspected through Firebase Console or Admin SDK logs rather than broad CLI reads. For backend auth failures, inspect Cloud Run logs for token verification errors and confirm `FIREBASE_CREDENTIALS_PATH` exists locally without printing its contents.

## Redis / Memorystore

```bash
gcloud redis instances list --project the49-487609 --region asia-southeast1
gcloud redis instances describe INSTANCE --project the49-487609 --region REGION
```

Check host, port, tier, memory size, state, region, auth settings, and connectivity from the Cloud Run VPC/network path.
