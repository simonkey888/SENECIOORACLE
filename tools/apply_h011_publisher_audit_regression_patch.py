"""Apply regression-test corrections discovered by the Linux publisher audit."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST = ROOT / "tests" / "h011_v3" / "test_h011_v3_publish_raw_scan.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    test = TEST.read_text(encoding="utf-8")

    test = replace_once(
        test,
        '''    if mutation == "hash":
        entry = _manifest(raw_dir, 0)
        entry["manifest_hash"] = "0" * 64
        (raw_dir / "manifest_000000.json").write_bytes(canonical_json_bytes(entry))
''',
        '''    if mutation == "hash":
        entry = _manifest(raw_dir, 0)
        entry["manifest_hash"] = "0" * 64
        manifest_path = raw_dir / "manifest_000000.json"
        manifest_path.chmod(0o644)
        try:
            manifest_path.write_bytes(canonical_json_bytes(entry))
        finally:
            manifest_path.chmod(0o444)
''',
        "controlled manifest corruption fixture",
    )

    test = replace_once(
        test,
        '''def test_short_write_preserves_marker_and_staging(
    raw_dir: Path, policy: MarkerValidationPolicy, monkeypatch,
):
    transfer = _transfer(raw_dir, "short-write")
    real_write = os.write
    calls = 0

    def short_write(fd, payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            return 0
        return real_write(fd, payload)

    monkeypatch.setattr(os, "write", short_write)
    with pytest.raises(PublishTransactionFailure):
        _publish(raw_dir, policy, transfer)
    assert len(_markers(raw_dir)) == 1
    assert (raw_dir / ".pending" / transfer.sealed.staging_filename).exists()
''',
        '''def test_short_write_preserves_marker_and_staging(
    raw_dir: Path, policy: MarkerValidationPolicy, monkeypatch,
):
    transfer = _transfer(raw_dir, "short-write")
    sealed = transfer.sealed
    real_write = os.write
    armed = False
    injected = False

    def hook(point: str):
        nonlocal armed
        if point == rt.FAULT_PUBLISH_AFTER_ARTIFACT_MARKER_UPDATE:
            armed = True

    def short_write(fd, payload):
        nonlocal armed, injected
        if armed and not injected:
            injected = True
            armed = False
            return 0
        return real_write(fd, payload)

    rt.set_fault_injection_hook(hook)
    monkeypatch.setattr(os, "write", short_write)
    with pytest.raises(PublishTransactionFailure) as raised:
        _publish(raw_dir, policy, transfer)

    assert injected is True
    assert raised.value.durable_marker_status == "ARTIFACT_PUBLISHED"
    assert raised.value.transfer_consumed is True
    assert transfer._closed is True
    assert len(_markers(raw_dir)) == 1
    marker = parse_marker(_markers(raw_dir)[0].read_bytes())
    assert marker["status"] == "ARTIFACT_PUBLISHED"
    assert (raw_dir / ".pending" / sealed.staging_filename).exists()
    assert (raw_dir / sealed.final_name).is_file()
    assert not (raw_dir / f"{sealed.final_name}.sha256").exists()
    assert not (raw_dir / "manifest_000000.json").exists()
    assert not _temps(raw_dir)
''',
        "short-write phase-scoped fault injection",
    )

    TEST.write_text(test, encoding="utf-8")


if __name__ == "__main__":
    main()
