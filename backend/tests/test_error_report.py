from urllib.parse import parse_qs, urlparse

from scripts.error_report import ErrorReportStore, sanitize_text


def test_sanitizer_removes_local_paths_and_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", r"C:\Users\Mario")
    text = (
        rf"{tmp_path}\backend\app.py C:\Users\Mario\AppData\config.json "
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456 "
        "access_token=super-secret-token"
    )

    cleaned = sanitize_text(text, tmp_path)

    assert str(tmp_path) not in cleaned
    assert "Mario" not in cleaned
    assert "super-secret-token" not in cleaned
    assert "abcdefghijklmnopqrstuvwxyz123456" not in cleaned
    assert "<APP_DIR>" in cleaned
    assert "<REDACTED>" in cleaned


def test_error_report_contains_actionable_diagnostics_and_prefilled_issue(tmp_path):
    app_root = tmp_path / "Savox Tool"
    store = ErrorReportStore(tmp_path / "reports", app_root, "9.8.7")

    try:
        raise RuntimeError(f"Kaputt in {app_root} mit token=abcdefghijklmnopqrstuvwxyz123456")
    except RuntimeError as exc:
        report = store.capture_exception(
            exc,
            "Arena-Kampf",
            context={"Arena-Phase": "battle", "Teilnehmerzahl": 48},
        )

    query = parse_qs(urlparse(report.issue_url).query)
    body = query["body"][0]
    assert report.fingerprint in query["title"][0]
    assert "v9.8.7" in body
    assert "Arena-Kampf" in body
    assert "Arena-Phase" in body
    assert "Teilnehmerzahl" in body
    assert "RuntimeError" in body
    assert "Stacktrace" in body
    assert str(app_root) not in body
    assert "abcdefghijklmnopqrstuvwxyz123456" not in body
    assert store.latest_path.is_file()
    assert (store.directory / report.report_file).is_file()


def test_identical_errors_are_deduplicated_for_ten_minutes(tmp_path):
    store = ErrorReportStore(tmp_path / "reports", tmp_path, "1.0.0")

    first = store.capture_text(
        error_type="FrontendError",
        message="WebGL context lost",
        trace="at render (App.tsx:42:1)",
        component="Browseroberfläche",
    )
    second = store.capture_text(
        error_type="FrontendError",
        message="WebGL context lost",
        trace="at render (App.tsx:42:1)",
        component="Browseroberfläche",
    )

    assert second.created_at == first.created_at
    assert second.fingerprint == first.fingerprint
    assert store.status()["issue_url"] == first.issue_url
