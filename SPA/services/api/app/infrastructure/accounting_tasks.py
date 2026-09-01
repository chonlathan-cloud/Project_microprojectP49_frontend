import json
from hashlib import sha256

from google.api_core.exceptions import AlreadyExists
from google.cloud import tasks_v2

from app.core.settings import Settings


class AccountingTaskUnavailable(Exception):
    pass


class AccountingTaskEnqueuer:
    def __init__(
        self,
        settings: Settings,
        client: tasks_v2.CloudTasksClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client or tasks_v2.CloudTasksClient()

    def enqueue_run(self, run_id: str) -> bool:
        settings = self._settings
        if settings.accounting_readiness_errors():
            raise AccountingTaskUnavailable("Accounting sync is not configured")
        assert settings.accounting_tasks_queue
        assert settings.accounting_worker_url
        assert settings.accounting_worker_oidc_audience
        assert settings.accounting_tasks_invoker_service_account
        digest = sha256(run_id.encode()).hexdigest()[:40]
        parent = self._client.queue_path(
            settings.gcp_project_id,
            settings.accounting_tasks_location,
            settings.accounting_tasks_queue,
        )
        task = {
            "name": self._client.task_path(
                settings.gcp_project_id,
                settings.accounting_tasks_location,
                settings.accounting_tasks_queue,
                f"run-{digest}",
            ),
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": (
                    f"{settings.accounting_worker_url.rstrip('/')}"
                    f"/internal/v1/tasks/accounting-runs/{run_id}"
                ),
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"runId": run_id}, separators=(",", ":")).encode(),
                "oidc_token": {
                    "service_account_email": settings.accounting_tasks_invoker_service_account,
                    "audience": settings.accounting_worker_oidc_audience,
                },
            },
        }
        try:
            self._client.create_task(request={"parent": parent, "task": task})
        except AlreadyExists:
            return False
        except Exception as error:
            raise AccountingTaskUnavailable("Accounting run task could not be created") from error
        return True
