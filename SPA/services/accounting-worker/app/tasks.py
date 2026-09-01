import asyncio
import json
from hashlib import sha256

from google.api_core.exceptions import AlreadyExists
from google.cloud import tasks_v2

from app.settings import Settings


class AccountingTaskEnqueuer:
    def __init__(
        self,
        settings: Settings,
        client: tasks_v2.CloudTasksClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client or tasks_v2.CloudTasksClient()

    def _create(self, *, task_id: str, path: str, body: dict[str, str]) -> bool:
        settings = self._settings
        if not (
            settings.tasks_queue
            and settings.worker_base_url
            and settings.tasks_invoker_service_account
            and settings.oidc_audience
        ):
            raise RuntimeError("Accounting Cloud Tasks configuration is incomplete")
        parent = self._client.queue_path(
            settings.gcp_project_id,
            settings.tasks_location,
            settings.tasks_queue,
        )
        task = {
            "name": self._client.task_path(
                settings.gcp_project_id,
                settings.tasks_location,
                settings.tasks_queue,
                task_id,
            ),
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{settings.worker_base_url.rstrip('/')}{path}",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(body, separators=(",", ":")).encode(),
                "oidc_token": {
                    "service_account_email": settings.tasks_invoker_service_account,
                    "audience": settings.oidc_audience,
                },
            },
        }
        try:
            self._client.create_task(request={"parent": parent, "task": task})
        except AlreadyExists:
            return False
        return True

    async def enqueue_run(self, run_id: str) -> bool:
        digest = sha256(run_id.encode()).hexdigest()[:40]
        return await asyncio.to_thread(
            self._create,
            task_id=f"run-{digest}",
            path=f"/internal/v1/tasks/accounting-runs/{run_id}",
            body={"runId": run_id},
        )

    async def enqueue_export(self, export_id: str, generation: int) -> bool:
        digest = sha256(export_id.encode()).hexdigest()[:40]
        return await asyncio.to_thread(
            self._create,
            task_id=f"export-{digest}-{generation}",
            path=f"/internal/v1/tasks/accounting-exports/{export_id}",
            body={"exportId": export_id},
        )
