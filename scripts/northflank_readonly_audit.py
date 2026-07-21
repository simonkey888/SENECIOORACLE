from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API = "https://api.northflank.com/v1"
TEAM_ID = "6a32fd953f19ee4079ccf395"
PROJECT = "seneciobot"
SERVICE = "senecio-h011"
TOKEN = os.environ["NORTHFLANK_API_TOKEN"]
OUT = Path("evidence")
LEDGER: list[dict[str, str]] = []

FORBIDDEN = (
    "secret", "secrets", "token", "password", "authorization", "cookie",
    "credential", "credentials", "runtimeenvironment", "runtimefiles",
    "environment", "env", "value", "privatekey",
)
PATTERNS = [
    re.compile(r"nf-[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"(?i)(authorization|cookie|set-cookie)\s*:\s*[^\r\n]+"),
    re.compile(r"(?i)(password|secret|credential|private[_-]?key|api[_-]?key)\s*[=:]\s*[^\s,;]+"),
]


def norm(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def forbidden_key(key: str) -> bool:
    normalized = norm(key)
    return any(fragment in normalized for fragment in FORBIDDEN)


def clean_text(text: str, limit: int = 1200) -> str:
    clean = text
    for pattern in PATTERNS:
        clean = pattern.sub("<redacted>", clean)
    return clean[:limit]


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): sanitize(child)
            for key, child in value.items()
            if not forbidden_key(str(key))
        }
    if isinstance(value, list):
        return [sanitize(child) for child in value]
    if isinstance(value, str):
        return clean_text(value)
    return value


def get(name: str, path: str, query: dict[str, Any] | None = None) -> dict[str, Any]:
    method = "GET"
    if method != "GET":
        raise RuntimeError("NON_GET_METHOD_BLOCKED")
    url = API + path
    if query:
        url += "?" + urllib.parse.urlencode(query, doseq=True)
    LEDGER.append({"name": name, "method": method, "path": path})
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = {"text": clean_text(raw)}
            return {"status": response.status, "body": body}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"text": clean_text(raw)}
        return {"status": exc.code, "body": body}


def data(result: dict[str, Any]) -> Any:
    body = result.get("body")
    return body.get("data") if isinstance(body, dict) else None


def values(value: Any, names: tuple[str, ...]) -> list[Any]:
    wanted = {norm(name) for name in names}
    found: list[Any] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if forbidden_key(str(key)):
                    continue
                if norm(str(key)) in wanted:
                    found.append(child)
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return found


def scalar(value: Any, names: tuple[str, ...]) -> Any:
    for candidate in values(value, names):
        if isinstance(candidate, (str, int, float, bool)) and candidate not in ("", None):
            return candidate
    return None


def entries(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get(key) or payload.get("data") or []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def log_findings(result: dict[str, Any]) -> dict[str, Any]:
    lines = data(result)
    lines = lines if isinstance(lines, list) else []
    counts = Counter()
    timestamps: list[str] = []
    samples: list[str] = []
    classifiers = {
        "error": re.compile(r"(?i)\b(error|exception|traceback|fatal)\b"),
        "warning": re.compile(r"(?i)\bwarn(?:ing)?\b"),
        "startup": re.compile(r"(?i)\b(startup|starting|started|uvicorn)\b"),
        "restart": re.compile(r"(?i)\b(restart|restarted|crash|killed)\b"),
        "scanner": re.compile(r"(?i)\b(scan|scanner|discovery)\b"),
        "filesystem": re.compile(r"(?i)\b(filesystem|volume|mount|fsync|flock|inode)\b"),
    }
    for item in lines:
        if not isinstance(item, dict):
            continue
        timestamp = item.get("ts")
        if isinstance(timestamp, str):
            timestamps.append(timestamp)
        text = clean_text(str(item.get("log") or ""), 500)
        for label, pattern in classifiers.items():
            if pattern.search(text):
                counts[label] += 1
        if text and len(samples) < 8:
            samples.append(text)
    return {
        "line_count": len(lines),
        "latest_timestamp": max(timestamps) if timestamps else None,
        "classified_counts": dict(counts),
        "samples": samples,
    }


def main() -> None:
    prefix = f"/teams/{TEAM_ID}/projects/{PROJECT}"
    service_path = f"{prefix}/services/{SERVICE}"
    requests: dict[str, dict[str, Any]] = {
        "team": get("team", f"/teams/{TEAM_ID}"),
        "project": get("project", prefix),
        "service": get("service", service_path),
        "deployment": get("deployment", f"{service_path}/deployment"),
        "ports": get("ports", f"{service_path}/ports"),
        "health_checks": get("health_checks", f"{service_path}/health-checks"),
        "containers": get("containers", f"{service_path}/containers", {"per_page": 100}),
        "builds": get("builds", f"{service_path}/build", {"per_page": 100}),
        "runtime_logs": get("runtime_logs", f"{service_path}/logs", {"type": "runtime", "queryType": "range", "duration": 604800, "lineLimit": 500, "direction": "backward"}),
        "build_logs": get("build_logs", f"{service_path}/build-logs", {"queryType": "range", "duration": 604800, "lineLimit": 300, "direction": "backward"}),
        "metrics": get("metrics", f"{service_path}/metrics", {"queryType": "single", "metricTypes": ["cpu", "memory", "diskUsage"]}),
        "volumes": get("volumes", f"{prefix}/volumes", {"per_page": 100}),
    }
    if requests["project"].get("status") != 200 or requests["service"].get("status") != 200:
        raise RuntimeError("AUTHENTICATED_LOOKUP_FAILED")

    project = data(requests["project"])
    service = data(requests["service"])
    deployment = data(requests["deployment"])
    project = project if isinstance(project, dict) else {}
    service = service if isinstance(service, dict) else {}
    deployment = deployment if isinstance(deployment, dict) else {}

    builds = entries(data(requests["builds"]), "builds")
    builds.sort(key=lambda item: str(item.get("createdAt") or item.get("updatedAt") or ""), reverse=True)
    latest_build = builds[0] if builds else {}
    build_id = str(latest_build.get("id") or "") or None
    build_detail: dict[str, Any] = {}
    if build_id:
        requests["build_detail"] = get("build_detail", f"{service_path}/build/{urllib.parse.quote(build_id)}")
        possible = data(requests["build_detail"])
        if isinstance(possible, dict):
            build_detail = possible

    containers = entries(data(requests["containers"]), "containers")
    statuses = Counter(str(item.get("status") or "UNKNOWN") for item in containers)
    restarts = [item for item in values(containers, ("restartCount", "restarts")) if isinstance(item, int)]

    volume_list = entries(data(requests["volumes"]), "volumes")
    attached: list[tuple[str, dict[str, Any]]] = []
    backups: dict[str, list[dict[str, Any]]] = {}
    for volume in volume_list:
        volume_id = str(volume.get("id") or "")
        if not volume_id:
            continue
        requests[f"volume_{volume_id}"] = get(f"volume_{volume_id}", f"{prefix}/volumes/{urllib.parse.quote(volume_id)}")
        detail = data(requests[f"volume_{volume_id}"])
        detail = detail if isinstance(detail, dict) else volume
        objects = detail.get("attachedObjects") if isinstance(detail.get("attachedObjects"), list) else []
        if any(SERVICE in {str(obj.get("id") or ""), str(obj.get("serviceId") or ""), str(obj.get("name") or "")} for obj in objects if isinstance(obj, dict)):
            attached.append((volume_id, detail))
        requests[f"backups_{volume_id}"] = get(f"backups_{volume_id}", f"{prefix}/volumes/{urllib.parse.quote(volume_id)}/backups", {"per_page": 100})
        backups[volume_id] = entries(data(requests[f"backups_{volume_id}"]), "backups")

    selected_id, selected = attached[0] if attached else (None, {})
    mount_paths = sorted({item for item in values(selected, ("containerMountPath", "mountPath", "path")) if isinstance(item, str) and item.startswith("/")})
    target_mount = any(path == "/app/polymarket/results" or path.startswith("/app/polymarket/results/") for path in mount_paths)
    if requests["volumes"].get("status") != 200:
        volume_present, storage_decision = "UNKNOWN", "STORAGE_CONFIGURATION_UNKNOWN"
    elif attached:
        volume_present = "YES"
        storage_decision = "STORAGE_PRESENT_AND_IDENTIFIED" if target_mount else "STORAGE_CONFIGURATION_UNKNOWN"
    else:
        volume_present, storage_decision = "NO", "STORAGE_ABSENT"

    backup_count = sum(len(items) for items in backups.values())
    if storage_decision == "STORAGE_PRESENT_AND_IDENTIFIED":
        safe_probe = "RESTORE_BACKUP_TO_ISOLATED_VOLUME_REQUIRES_SEPARATE_AUTHORIZATION" if backup_count else "CREATE_NEW_TEMPORARY_VOLUME_REQUIRES_SEPARATE_AUTHORIZATION"
    elif storage_decision == "STORAGE_ABSENT":
        safe_probe = "CREATE_NEW_TEMPORARY_VOLUME_OR_DIAGNOSTIC_SERVICE_REQUIRES_SEPARATE_AUTHORIZATION"
    else:
        safe_probe = "NO_SAFE_PROBE_ENVIRONMENT_IDENTIFIED"

    report = sanitize({
        "validated_sha": os.environ.get("GITHUB_SHA"),
        "northflank_access": "YES",
        "project_id": project.get("id") or PROJECT,
        "project_region": project.get("region") or scalar(project, ("region",)),
        "service_id": service.get("id") or SERVICE,
        "service_type": service.get("serviceType") or scalar(service, ("serviceType", "type")),
        "repository": scalar(service, ("repository", "projectUrl", "repoUrl", "repositoryUrl")),
        "branch": build_detail.get("branch") or latest_build.get("branch") or scalar(service, ("branch", "branchName")),
        "build_context": scalar(service, ("buildContext", "dockerWorkDir", "context")),
        "dockerfile": scalar(service, ("dockerfilePath", "dockerfile")),
        "build_id": build_id,
        "deployment_id": scalar(deployment, ("deploymentId", "id")),
        "deployed_sha": build_detail.get("sha") or latest_build.get("sha") or scalar(deployment, ("sha", "commitSha", "deployedSha")) or scalar(service, ("sha", "commitSha", "deployedSha")),
        "image_digest": scalar([service, deployment, build_detail], ("imageDigest", "digest")),
        "runtime_command": scalar(deployment, ("command", "cmd", "entrypoint", "entryPoint")),
        "ports": data(requests["ports"]),
        "health_checks": data(requests["health_checks"]) or service.get("healthChecks"),
        "restart_state": {"container_statuses": dict(statuses), "restart_count_max": max(restarts) if restarts else None},
        "replicas": scalar(deployment, ("instances", "replicas", "replicaCount")),
        "containers": containers,
        "volume_present": volume_present,
        "volume_id": selected_id,
        "volume_name": selected.get("name") or scalar(selected, ("name",)),
        "mount_path": mount_paths,
        "storage_class": scalar(selected, ("storageClassName", "storageClass")),
        "capacity": scalar(selected, ("storageSize", "capacity", "size")),
        "access_mode": scalar(selected, ("accessMode", "volumeAccessMode")),
        "persistence": "PERSISTENT_VOLUME_ATTACHED" if volume_present == "YES" else ("NO_PERSISTENT_VOLUME_ATTACHED" if volume_present == "NO" else "UNKNOWN"),
        "backups_available": "YES" if backup_count else "NO",
        "recent_log_findings": {"runtime": log_findings(requests["runtime_logs"]), "build": log_findings(requests["build_logs"])},
        "storage_decision": storage_decision,
        "safe_probe_option": safe_probe,
        "mutating_requests": 0,
        "sensitive_values_captured": 0,
        "production_changed": "NO",
        "deploy_executed": "NO",
        "pr5_changed": "NO",
        "pr21_changed": "NO",
        "request_ledger": LEDGER,
        "request_statuses": {name: result.get("status") for name, result in requests.items()},
    })
    OUT.mkdir(exist_ok=True)
    OUT.joinpath("northflank-readonly-report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    OUT.joinpath("northflank-readonly-summary.txt").write_text("\n".join(f"{key.upper()}={json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else ('UNKNOWN' if value in (None, '') else value)}" for key, value in report.items() if key not in {"request_ledger", "request_statuses"}) + "\nMUTATING_REQUESTS=0\nSENSITIVE_VALUES_CAPTURED=0\n", encoding="utf-8")
    if any(item.get("method") != "GET" for item in LEDGER):
        raise RuntimeError("NON_GET_REQUEST_DETECTED")


if __name__ == "__main__":
    main()
