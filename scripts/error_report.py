from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import tempfile
import traceback
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from importlib import metadata
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlencode

GITHUB_OWNER = "Savox76"
GITHUB_REPOSITORY = "savox76-giveaway"
GITHUB_REPOSITORY_FULL_NAME = f"{GITHUB_OWNER}/{GITHUB_REPOSITORY}"
GITHUB_NEW_ISSUE_URL = f"https://github.com/{GITHUB_REPOSITORY_FULL_NAME}/issues/new"
REPORT_FORMAT = 1
MAX_MESSAGE_LENGTH = 500
MAX_TRACE_LENGTH = 6500
MAX_CONTEXT_VALUE_LENGTH = 600
DEDUPLICATION_MINUTES = 10

_SECRET_PATTERNS = (
    re.compile(
        r"(?i)((?:authorization|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
        r"device[_-]?code|user[_-]?code)\s*[\"']?\s*[:=]\s*[\"']?)([^\s\"',;}]+)"
    ),
    re.compile(r"(?i)(\b(?:bearer|oauth)\s+)([^\s\"',;}]+)"),
    re.compile(r"(?i)([?&](?:token|access_token|refresh_token|code|client_secret)=)([^&#\s]+)"),
)
_GENERIC_TOKEN_PATTERN = re.compile(r"\b(?:oauth:)?[a-zA-Z0-9_-]{32,}\b")
_WINDOWS_USER_PATH = re.compile(r"(?i)\b([a-z]:\\Users\\)[^\\\s]+")
_UNIX_USER_PATH = re.compile(r"(?<![\w.-])(/(?:home|Users)/)[^/\s]+")
_UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)


@dataclass(slots=True)
class ErrorReport:
    format: int
    created_at: str
    fingerprint: str
    component: str
    error_type: str
    summary: str
    title: str
    body: str
    issue_url: str
    report_file: str = ""

    def status(self) -> dict[str, Any]:
        return {
            "available": True,
            "created_at": self.created_at,
            "fingerprint": self.fingerprint,
            "component": self.component,
            "error_type": self.error_type,
            "summary": self.summary,
            "issue_url": self.issue_url,
        }


def sanitize_text(value: Any, app_root: Path | None = None) -> str:
    """Entfernt lokale Pfade und bekannte Geheimnisformate aus Diagnoseangaben."""
    text = str(value or "")
    replacements: list[tuple[str, str]] = []
    if app_root is not None:
        replacements.append((str(app_root.resolve()), "<APP_DIR>"))
    with_home = Path.home()
    replacements.append((str(with_home), "<HOME>"))
    for name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        raw = os.environ.get(name, "").strip()
        if raw:
            replacements.append((raw, f"<{name}>"))
    for raw, replacement in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        text = text.replace(raw, replacement)
        text = text.replace(raw.replace("\\", "/"), replacement)
    text = _WINDOWS_USER_PATH.sub(r"\1<USER>", text)
    text = _UNIX_USER_PATH.sub(r"\1<USER>", text)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1<REDACTED>", text)
    text = _GENERIC_TOKEN_PATTERN.sub("<POSSIBLE_TOKEN_REDACTED>", text)
    return text.replace("\x00", "")


class ErrorReportStore:
    def __init__(self, directory: Path, app_root: Path, version: str) -> None:
        self.directory = directory
        self.app_root = app_root
        self.version = version
        self.latest_path = directory / "last-error-report.json"
        self._lock = RLock()

    def capture_exception(
        self,
        exc: BaseException,
        component: str,
        *,
        context: dict[str, Any] | None = None,
        traceback_text: str | None = None,
    ) -> ErrorReport:
        rendered_trace = traceback_text or "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        return self.capture_text(
            error_type=type(exc).__name__,
            message=str(exc) or repr(exc),
            trace=rendered_trace,
            component=component,
            context=context,
        )

    def capture_text(
        self,
        *,
        error_type: str,
        message: str,
        trace: str,
        component: str,
        context: dict[str, Any] | None = None,
    ) -> ErrorReport:
        safe_type = self._compact(sanitize_text(error_type, self.app_root), 100) or "UnknownError"
        safe_message = self._compact(sanitize_text(message, self.app_root), MAX_MESSAGE_LENGTH)
        safe_component = self._compact(sanitize_text(component, self.app_root), 160)
        safe_trace = sanitize_text(trace, self.app_root).strip()
        if len(safe_trace) > MAX_TRACE_LENGTH:
            safe_trace = "… Stacktrace am Anfang gekürzt …\n" + safe_trace[-MAX_TRACE_LENGTH:]
        safe_context = {
            self._compact(sanitize_text(key, self.app_root), 80): self._compact(
                sanitize_text(value, self.app_root), MAX_CONTEXT_VALUE_LENGTH
            )
            for key, value in (context or {}).items()
            if value is not None
        }
        fingerprint = self._fingerprint(safe_type, safe_message, safe_trace, safe_component)
        with self._lock:
            previous = self._load()
            if previous and previous.fingerprint == fingerprint and self._is_recent(previous):
                return previous
            created_at = datetime.now(UTC).isoformat()
            body = self._build_body(
                created_at=created_at,
                fingerprint=fingerprint,
                component=safe_component,
                error_type=safe_type,
                message=safe_message,
                trace=safe_trace,
                context=safe_context,
            )
            title = self._compact(
                f"[Tool-Fehler] {safe_type} · {safe_component} · {fingerprint}", 180
            )
            issue_url = f"{GITHUB_NEW_ISSUE_URL}?{urlencode({'title': title, 'body': body})}"
            report = ErrorReport(
                format=REPORT_FORMAT,
                created_at=created_at,
                fingerprint=fingerprint,
                component=safe_component,
                error_type=safe_type,
                summary=safe_message,
                title=title,
                body=body,
                issue_url=issue_url,
            )
            self._save(report)
            return report

    def latest(self, max_age_seconds: int | None = None) -> ErrorReport | None:
        with self._lock:
            report = self._load()
        if report is None or max_age_seconds is None:
            return report
        try:
            created = datetime.fromisoformat(report.created_at)
        except ValueError:
            return None
        if datetime.now(UTC) - created > timedelta(seconds=max_age_seconds):
            return None
        return report

    def status(self) -> dict[str, Any]:
        report = self.latest()
        return report.status() if report else {"available": False}

    def _build_body(
        self,
        *,
        created_at: str,
        fingerprint: str,
        component: str,
        error_type: str,
        message: str,
        trace: str,
        context: dict[str, str],
    ) -> str:
        dependencies = self._dependency_versions()
        context_lines = "\n".join(f"- **{key}:** `{value}`" for key, value in context.items())
        dependency_lines = " · ".join(f"{name} {version}" for name, version in dependencies.items())
        return (
            "## Automatisch erstellter Fehlerbericht\n\n"
            "> Der Bericht wurde lokal erzeugt und vor dem Öffnen von GitHub bereinigt. "
            "Bitte kurz prüfen und anschließend absenden.\n\n"
            "### Fehler\n\n"
            f"- **Version:** `v{self.version}`\n"
            f"- **Komponente:** `{component}`\n"
            f"- **Fehlertyp:** `{error_type}`\n"
            f"- **Fingerabdruck:** `{fingerprint}`\n"
            f"- **Zeitpunkt (UTC):** `{created_at}`\n\n"
            f"```text\n{message}\n```\n\n"
            "### System\n\n"
            f"- **Betriebssystem:** `{sanitize_text(platform.platform(), self.app_root)}`\n"
            f"- **Architektur:** `{platform.machine() or 'unbekannt'}`\n"
            f"- **Python:** `{platform.python_version()}`\n"
            f"- **Pakete:** `{dependency_lines or 'nicht ermittelbar'}`\n"
            + (f"\n### Laufzeitkontext\n\n{context_lines}\n" if context_lines else "")
            + "\n### Stacktrace\n\n"
            "<details><summary>Bereinigten Stacktrace anzeigen</summary>\n\n"
            f"```text\n{trace or 'Kein Stacktrace verfügbar.'}\n```\n\n"
            "</details>\n\n"
            "### Was ist unmittelbar davor passiert?\n\n"
            "<!-- Bitte in einem kurzen Satz ergänzen, falls bekannt. -->\n\n"
            "### Datenschutzprüfung\n\n"
            "- [ ] Ich habe geprüft, dass der Bericht keine persönlichen Daten oder Tokens enthält.\n"
        )

    @staticmethod
    def _dependency_versions() -> dict[str, str]:
        versions: dict[str, str] = {}
        for package in ("fastapi", "uvicorn", "httpx", "websockets", "keyring"):
            try:
                versions[package] = metadata.version(package)
            except metadata.PackageNotFoundError:
                continue
        return versions

    @staticmethod
    def _compact(value: str, limit: int) -> str:
        single_line = " ".join(value.split())
        return single_line if len(single_line) <= limit else single_line[: limit - 1] + "…"

    @staticmethod
    def _fingerprint(error_type: str, message: str, trace: str, component: str) -> str:
        stable = "\n".join((error_type, message, component, trace[-1800:]))
        stable = _UUID_PATTERN.sub("<UUID>", stable)
        stable = re.sub(r"\b0x[0-9a-fA-F]+\b", "<HEX>", stable)
        stable = re.sub(r"\b\d{4,}\b", "<NUMBER>", stable)
        return hashlib.sha256(stable.encode("utf-8", errors="replace")).hexdigest()[:12]

    @staticmethod
    def _is_recent(report: ErrorReport) -> bool:
        try:
            created = datetime.fromisoformat(report.created_at)
        except ValueError:
            return False
        return datetime.now(UTC) - created < timedelta(minutes=DEDUPLICATION_MINUTES)

    def _load(self) -> ErrorReport | None:
        try:
            payload = json.loads(self.latest_path.read_text(encoding="utf-8"))
            if payload.get("format") != REPORT_FORMAT:
                return None
            return ErrorReport(**payload)
        except (OSError, ValueError, TypeError):
            return None

    def _save(self, report: ErrorReport) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            stamp = report.created_at.replace(":", "-").replace("+", "_")
            markdown_path = self.directory / f"{stamp}-{report.fingerprint}.md"
            markdown_path.write_text(f"# {report.title}\n\n{report.body}", encoding="utf-8")
            report.report_file = markdown_path.name
            handle, temporary = tempfile.mkstemp(
                prefix="error-report-", suffix=".json", dir=self.directory
            )
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    json.dump(asdict(report), stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
                os.replace(temporary, self.latest_path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            self._prune_markdown_reports()
        except OSError:
            report.report_file = ""

    def _prune_markdown_reports(self) -> None:
        reports = sorted(self.directory.glob("*-????????????.md"), reverse=True)
        for obsolete in reports[10:]:
            try:
                obsolete.unlink()
            except OSError:
                pass


def open_issue_report(report: ErrorReport) -> bool:
    try:
        import webbrowser

        return bool(webbrowser.open(report.issue_url))
    except Exception:
        return False
