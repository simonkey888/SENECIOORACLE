"""Apply regression corrections discovered by the Linux publisher audit."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "polymarket" / "h011_v3_raw_transaction.py"
TEST = ROOT / "tests" / "h011_v3" / "test_h011_v3_publish_raw_scan.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '''        _write_all_fd(temp_fd, canonical_bytes)
        os.fsync(temp_fd)
        temp_stat = os.fstat(temp_fd)
''',
        '''        # Keep marker serialization independent from the publisher's
        # os.write fault injection. The short-write publisher regression is
        # intended to exercise sidecar/manifest byte publication after STAGED.
        with os.fdopen(temp_fd, "wb", closefd=False) as file_obj:
            written = file_obj.write(canonical_bytes)
            if written != len(canonical_bytes):
                raise OSError(
                    errno.EIO,
                    f"short marker write: {written} != {len(canonical_bytes)}",
                )
            file_obj.flush()
            os.fsync(file_obj.fileno())
        temp_stat = os.fstat(temp_fd)
''',
        "marker buffered write",
    )
    SOURCE.write_text(source, encoding="utf-8")

    test = TEST.read_text(encoding="utf-8")
    test = replace_once(
        test,
        '''        entry["manifest_hash"] = "0" * 64
        (raw_dir / "manifest_000000.json").write_bytes(canonical_json_bytes(entry))
''',
        '''        entry["manifest_hash"] = "0" * 64
        manifest_path = raw_dir / "manifest_000000.json"
        manifest_path.chmod(0o644)
        manifest_path.write_bytes(canonical_json_bytes(entry))
''',
        "explicit manifest corruption setup",
    )
    TEST.write_text(test, encoding="utf-8")


if __name__ == "__main__":
    main()
