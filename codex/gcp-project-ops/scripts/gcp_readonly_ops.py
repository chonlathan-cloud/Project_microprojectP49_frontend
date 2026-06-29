#!/usr/bin/env python3
"""Read-only Google Cloud diagnostics for project the49-487609."""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request


PROJECT_ID = "the49-487609"
DEFAULT_REGION = "asia-southeast1"
DEFAULT_DATABASE = "(default)"


def require_tool(name: str) -> bool:
    if shutil.which(name):
        return True
    print(f"[missing] {name} is not installed or is not on PATH", file=sys.stderr)
    return False


def run_cmd(args: list[str], dry_run: bool, timeout: int = 90) -> int:
    print("\n$ " + shlex.join(args))
    if dry_run:
        return 0
    try:
        completed = subprocess.run(
            args,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except FileNotFoundError:
        print(f"[missing] {args[0]} is not installed or is not on PATH", file=sys.stderr)
        return 127
    except subprocess.TimeoutExpired:
        print(f"[timeout] command exceeded {timeout}s", file=sys.stderr)
        return 124

    if completed.stdout:
        print(completed.stdout.rstrip())
    if completed.stderr:
        print(completed.stderr.rstrip(), file=sys.stderr)
    return completed.returncode


def gcloud(base: list[str], args: argparse.Namespace) -> list[str]:
    cmd = ["gcloud", *base, "--project", args.project]
    if args.output == "json":
        cmd.append("--format=json")
    return cmd


def inventory(args: argparse.Namespace) -> int:
    commands = [
        ["gcloud", "config", "get-value", "project"],
        gcloud(["services", "list", "--enabled"], args),
        gcloud(["run", "services", "list", "--platform", "managed", "--region", args.region], args),
        gcloud(["run", "jobs", "list", "--region", args.region], args),
        gcloud(["storage", "buckets", "list"], args),
        ["bq", "ls", "--project_id", args.project, "--format=json" if args.output == "json" else "--format=pretty"],
        gcloud(["firestore", "databases", "list"], args),
        gcloud(["documentai", "processors", "list", "--location", args.region], args),
        gcloud(["ai", "models", "list", "--region", args.region], args),
        gcloud(["ai", "endpoints", "list", "--region", args.region], args),
        gcloud(["redis", "instances", "list", "--region", args.region], args),
    ]
    rc = 0
    for command in commands:
        rc = max(rc, run_cmd(command, args.dry_run))
    return rc


def cloud_run(args: argparse.Namespace) -> int:
    if not args.service:
        return run_cmd(gcloud(["run", "services", "list", "--platform", "managed", "--region", args.region], args), args.dry_run)
    commands = [
        gcloud(["run", "services", "describe", args.service, "--region", args.region], args),
        gcloud(["run", "revisions", "list", "--service", args.service, "--region", args.region], args),
    ]
    rc = 0
    for command in commands:
        rc = max(rc, run_cmd(command, args.dry_run))
    return rc


def logs(args: argparse.Namespace) -> int:
    filters = [
        'resource.type="cloud_run_revision"',
        f'resource.labels.service_name="{args.service}"',
    ]
    if args.severity:
        filters.append(f"severity>={args.severity}")
    query = " AND ".join(filters)
    command = [
        "gcloud",
        "logging",
        "read",
        query,
        "--project",
        args.project,
        "--freshness",
        args.freshness,
        "--limit",
        str(args.limit),
    ]
    if args.output == "json":
        command.append("--format=json")
    return run_cmd(command, args.dry_run)


def bigquery(args: argparse.Namespace) -> int:
    fmt = "--format=json" if args.output == "json" else "--format=pretty"
    if not args.dataset:
        return run_cmd(["bq", "ls", "--project_id", args.project, fmt], args.dry_run)
    if not args.table:
        return run_cmd(["bq", "ls", fmt, f"{args.project}:{args.dataset}"], args.dry_run)

    table_ref = f"{args.project}:{args.dataset}.{args.table}"
    commands = [["bq", "show", "--schema", "--format=prettyjson", table_ref]]
    if args.sample:
        sql = f"SELECT * FROM `{args.project}.{args.dataset}.{args.table}` LIMIT {args.limit}"
        commands.append(["bq", "query", "--nouse_legacy_sql", f"--max_rows={args.limit}", sql])

    rc = 0
    for command in commands:
        rc = max(rc, run_cmd(command, args.dry_run))
    return rc


def firestore_token() -> str:
    completed = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    return completed.stdout.strip()


def firestore_request(url: str, args: argparse.Namespace) -> int:
    print("\nGET " + url)
    if args.dry_run:
        return 0
    try:
        token = firestore_token()
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read().decode("utf-8")
    except subprocess.CalledProcessError as exc:
        print(exc.stderr.rstrip(), file=sys.stderr)
        return exc.returncode
    except Exception as exc:  # urllib raises several concrete HTTP exceptions.
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    parsed = json.loads(payload) if payload else {}
    print(json.dumps(parsed, indent=2, sort_keys=True))
    return 0


def firestore(args: argparse.Namespace) -> int:
    rc = run_cmd(gcloud(["firestore", "databases", "list"], args), args.dry_run)
    if not args.path:
        return rc

    encoded_path = urllib.parse.quote(args.path.strip("/"), safe="/")
    database = urllib.parse.quote(args.database, safe="")
    if args.document:
        url = f"https://firestore.googleapis.com/v1/projects/{args.project}/databases/{database}/documents/{encoded_path}"
    else:
        url = (
            f"https://firestore.googleapis.com/v1/projects/{args.project}/databases/{database}"
            f"/documents/{encoded_path}?pageSize={args.limit}"
        )
    return max(rc, firestore_request(url, args))


def documentai(args: argparse.Namespace) -> int:
    if not args.processor:
        return run_cmd(gcloud(["documentai", "processors", "list", "--location", args.region], args), args.dry_run)
    return run_cmd(
        gcloud(["documentai", "processors", "describe", args.processor, "--location", args.region], args),
        args.dry_run,
    )


def vertex(args: argparse.Namespace) -> int:
    commands = [
        gcloud(["ai", "models", "list", "--region", args.region], args),
        gcloud(["ai", "endpoints", "list", "--region", args.region], args),
    ]
    rc = 0
    for command in commands:
        rc = max(rc, run_cmd(command, args.dry_run))
    return rc


def storage(args: argparse.Namespace) -> int:
    if not args.bucket:
        return run_cmd(gcloud(["storage", "buckets", "list"], args), args.dry_run)
    return run_cmd(["gcloud", "storage", "ls", f"gs://{args.bucket}", "--project", args.project], args.dry_run)


def redis(args: argparse.Namespace) -> int:
    if not args.instance:
        return run_cmd(gcloud(["redis", "instances", "list", "--region", args.region], args), args.dry_run)
    return run_cmd(gcloud(["redis", "instances", "describe", args.instance, "--region", args.region], args), args.dry_run)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=PROJECT_ID)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--output", choices=["table", "json"], default="table")
    parser.add_argument("--dry-run", action="store_true", help="Print commands/URLs without executing them.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("inventory")

    run_parser = subparsers.add_parser("cloud-run")
    run_parser.add_argument("--service")

    logs_parser = subparsers.add_parser("logs")
    logs_parser.add_argument("--service", required=True)
    logs_parser.add_argument("--severity", default="ERROR")
    logs_parser.add_argument("--freshness", default="2h")
    logs_parser.add_argument("--limit", type=int, default=100)

    bq_parser = subparsers.add_parser("bigquery")
    bq_parser.add_argument("--dataset")
    bq_parser.add_argument("--table")
    bq_parser.add_argument("--sample", action="store_true")
    bq_parser.add_argument("--limit", type=int, default=20)

    fs_parser = subparsers.add_parser("firestore")
    fs_parser.add_argument("--database", default=DEFAULT_DATABASE)
    fs_parser.add_argument("--path", help="Collection path, or document path when --document is set.")
    fs_parser.add_argument("--document", action="store_true")
    fs_parser.add_argument("--limit", type=int, default=20)

    docai_parser = subparsers.add_parser("documentai")
    docai_parser.add_argument("--processor")

    subparsers.add_parser("vertex")

    storage_parser = subparsers.add_parser("storage")
    storage_parser.add_argument("--bucket")

    redis_parser = subparsers.add_parser("redis")
    redis_parser.add_argument("--instance")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    missing = False
    if args.command in {"inventory", "cloud-run", "logs", "firestore", "documentai", "vertex", "storage", "redis"}:
        missing = not require_tool("gcloud") or missing
    if args.command in {"inventory", "bigquery"}:
        missing = not require_tool("bq") or missing
    if missing:
        return 127

    handlers = {
        "inventory": inventory,
        "cloud-run": cloud_run,
        "logs": logs,
        "bigquery": bigquery,
        "firestore": firestore,
        "documentai": documentai,
        "vertex": vertex,
        "storage": storage,
        "redis": redis,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
