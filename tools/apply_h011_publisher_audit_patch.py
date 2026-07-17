"""One-shot exact patcher for the H-011 publisher hostile audit branch."""
from __future__ import annotations

import re
from pathlib import Path


TARGET = Path("polymarket/h011_v3_raw_transaction.py")


CREATE_MARKER_REPLACEMENT = r'''def create_marker_no_replace_under_lock(
    guard: "RawChainLockGuard",
    directory: Path,
    marker_name: str,
    marker_body: dict[str, Any],
    policy: MarkerValidationPolicy,
) -> Path:
    """Create and durably verify a marker without replacing any destination.

    The temporary marker name is made durable before linking the canonical
    name. The canonical hardlink is verified by bytes and inode identity both
    before and after directory commit, and the source link is never followed
    if it is raced into a symlink.
    """
    assert_guard_valid(guard, directory, policy.manifest_prefix)
    validate_bare_filename(marker_name)
    canonical_bytes = prepare_validated_marker_bytes(marker_body, policy)
    canonical_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
    dir_fd = guard.trusted.fd

    try:
        existing_fd = os.open(
            marker_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd
        )
        os.close(existing_fd)
        raise FileExistsError(
            f"marker already exists: {marker_name} — "
            "use update_existing_marker_atomic_under_lock"
        )
    except FileNotFoundError:
        pass
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise PathSafetyError(
                f"existing marker path is a symlink: {marker_name}"
            ) from exc
        raise

    temp_name = f"{marker_name}.tmp.{uuid.uuid4().hex}"
    temp_fd = -1
    try:
        temp_fd = os.open(
            temp_name,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
            0o644,
            dir_fd=dir_fd,
        )
        _write_all_fd(temp_fd, canonical_bytes)
        os.fsync(temp_fd)
        temp_stat = os.fstat(temp_fd)
        if not statmod.S_ISREG(temp_stat.st_mode):
            raise PathSafetyError(
                f"marker temp is not a regular file: {temp_name}"
            )
    except BaseException as exc:
        close_error: OSError | None = None
        if temp_fd >= 0:
            try:
                os.close(temp_fd)
            except OSError as inner_exc:
                close_error = inner_exc
            temp_fd = -1
        temp_unlinked, confirmed, cleanup_error = _cleanup_temp_durably(
            dir_fd, temp_name
        )
        if close_error is not None or not confirmed:
            raise MarkerCreateCleanupPending(
                f"marker temp preparation failed ({exc}); "
                f"close_error={close_error}; cleanup={cleanup_error}",
                final_created=False,
                temp_unlinked=temp_unlinked,
                cleanup_durability_confirmed=confirmed,
                filesystem_state="PRE_COMMIT_CLEANUP_UNCONFIRMED",
            ) from exc
        _mark_precommit_failed_clean(exc)
        raise
    try:
        os.close(temp_fd)
    except OSError as exc:
        temp_unlinked, confirmed, cleanup_error = _cleanup_temp_durably(
            dir_fd, temp_name
        )
        raise MarkerCreateCleanupPending(
            f"marker temp close failed ({exc}); cleanup={cleanup_error}",
            final_created=False,
            temp_unlinked=temp_unlinked,
            cleanup_durability_confirmed=confirmed,
            filesystem_state=(
                "PRE_COMMIT_FAILED_CLEAN"
                if confirmed
                else "PRE_COMMIT_CLEANUP_UNCONFIRMED"
            ),
        ) from exc
    temp_fd = -1

    # Make the temp directory entry durable. A crash before the canonical link
    # can therefore be detected as an explicit marker-temp residue.
    try:
        _dir_fsync_via_fd(dir_fd)
    except OSError as exc:
        temp_unlinked, confirmed, cleanup_error = _cleanup_temp_durably(
            dir_fd, temp_name
        )
        if not confirmed:
            raise MarkerCreateCleanupPending(
                f"marker temp durability failed ({exc}); "
                f"cleanup={cleanup_error}",
                final_created=False,
                temp_unlinked=temp_unlinked,
                cleanup_durability_confirmed=False,
                filesystem_state="PRE_COMMIT_CLEANUP_UNCONFIRMED",
            ) from exc
        _mark_precommit_failed_clean(exc)
        raise

    try:
        temp_stat = _verify_published_file_fd(
            dir_fd=dir_fd,
            name=temp_name,
            expected_bytes=canonical_bytes,
            expected_sha256=canonical_sha256,
        )
    except BaseException as exc:
        temp_unlinked, confirmed, cleanup_error = _cleanup_temp_durably(
            dir_fd, temp_name
        )
        if not confirmed:
            raise MarkerCreateCleanupPending(
                f"marker temp verification failed ({exc}); "
                f"cleanup={cleanup_error}",
                final_created=False,
                temp_unlinked=temp_unlinked,
                cleanup_durability_confirmed=False,
                filesystem_state="PRE_COMMIT_CLEANUP_UNCONFIRMED",
            ) from exc
        _mark_precommit_failed_clean(exc)
        raise

    expected_identity = (
        temp_stat.st_dev,
        temp_stat.st_ino,
        temp_stat.st_size,
    )
    try:
        os.link(
            temp_name,
            marker_name,
            src_dir_fd=dir_fd,
            dst_dir_fd=dir_fd,
            follow_symlinks=False,
        )
    except BaseException as exc:
        temp_unlinked, confirmed, cleanup_error = _cleanup_temp_durably(
            dir_fd, temp_name
        )
        if not confirmed:
            raise MarkerCreateCleanupPending(
                f"marker final link failed ({exc}); cleanup={cleanup_error}",
                final_created=False,
                temp_unlinked=temp_unlinked,
                cleanup_durability_confirmed=False,
                filesystem_state="PRE_COMMIT_CLEANUP_UNCONFIRMED",
            ) from exc
        _mark_precommit_failed_clean(exc)
        raise

    try:
        _inject_fault(FAULT_CREATE_AFTER_FINAL_LINK)
    except BaseException as exc:
        raise MarkerCreateCleanupPending(
            f"final marker link exists but temp link remains and directory "
            f"durability is not confirmed: {exc}",
            final_created=True,
            temp_unlinked=False,
            cleanup_durability_confirmed=False,
            filesystem_state="COMMITTED_OLD_TEMP_PRESENT",
        ) from exc

    try:
        _verify_published_file_fd(
            dir_fd=dir_fd,
            name=marker_name,
            expected_bytes=canonical_bytes,
            expected_sha256=canonical_sha256,
            expected_identity=expected_identity,
        )
    except BaseException as exc:
        raise MarkerCreateCleanupPending(
            f"canonical marker verification failed before directory commit: {exc}",
            final_created=True,
            temp_unlinked=False,
            cleanup_durability_confirmed=False,
            filesystem_state="COMMITTED_OLD_TEMP_PRESENT",
        ) from exc

    # First directory fsync is the canonical-marker commit point. Keep the
    # temp hardlink until this succeeds so at least one verified name remains.
    try:
        _dir_fsync_via_fd(dir_fd)
    except OSError as exc:
        raise MarkerCreateCleanupPending(
            f"canonical marker link exists but first directory fsync failed: {exc}",
            final_created=True,
            temp_unlinked=False,
            cleanup_durability_confirmed=False,
            filesystem_state="COMMITTED_OLD_TEMP_PRESENT",
        ) from exc

    try:
        _verify_published_file_fd(
            dir_fd=dir_fd,
            name=marker_name,
            expected_bytes=canonical_bytes,
            expected_sha256=canonical_sha256,
            expected_identity=expected_identity,
        )
    except BaseException as exc:
        raise MarkerCreateCleanupPending(
            f"canonical marker changed after directory commit: {exc}",
            final_created=True,
            temp_unlinked=False,
            cleanup_durability_confirmed=False,
            filesystem_state="COMMITTED_OLD_TEMP_PRESENT",
        ) from exc

    try:
        os.unlink(temp_name, dir_fd=dir_fd)
    except OSError as exc:
        raise MarkerCreateCleanupPending(
            f"canonical marker is committed but temp unlink failed: {exc}",
            final_created=True,
            temp_unlinked=False,
            cleanup_durability_confirmed=False,
            filesystem_state="COMMITTED_OLD_TEMP_PRESENT",
        ) from exc

    try:
        _inject_fault(FAULT_CREATE_AFTER_TEMP_UNLINK)
    except BaseException as exc:
        raise MarkerCreateCleanupPending(
            f"canonical marker is committed and temp is absent, but cleanup "
            f"fsync is pending: {exc}",
            final_created=True,
            temp_unlinked=True,
            cleanup_durability_confirmed=False,
            filesystem_state="COMMITTED_OLD_TEMP_REMOVED_FSYNC_UNCONFIRMED",
        ) from exc

    try:
        _dir_fsync_via_fd(dir_fd)
    except OSError as exc:
        raise MarkerCreateCleanupPending(
            f"canonical marker is committed and temp was unlinked; second "
            f"directory fsync failed: {exc}",
            final_created=True,
            temp_unlinked=True,
            cleanup_durability_confirmed=False,
            filesystem_state="COMMITTED_OLD_TEMP_REMOVED_FSYNC_UNCONFIRMED",
        ) from exc

    try:
        _verify_published_file_fd(
            dir_fd=dir_fd,
            name=marker_name,
            expected_bytes=canonical_bytes,
            expected_sha256=canonical_sha256,
            expected_identity=expected_identity,
        )
    except BaseException as exc:
        raise MarkerCreateCleanupPending(
            f"canonical marker changed after committed-clean publication: {exc}",
            final_created=True,
            temp_unlinked=True,
            cleanup_durability_confirmed=True,
            filesystem_state="COMMITTED_CLEAN",
        ) from exc

    try:
        _inject_fault(FAULT_CREATE_AFTER_DIR_FSYNC)
    except BaseException as exc:
        raise MarkerPostCommitNotificationError(
            f"marker creation is committed-clean; post-commit hook failed: {exc}",
            operation="create",
        ) from exc
    return directory / marker_name
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")

    create_pattern = re.compile(
        r"def create_marker_no_replace_under_lock\(.*?\n\ndef _snapshot_dir_entry",
        re.DOTALL,
    )
    text, count = create_pattern.subn(
        CREATE_MARKER_REPLACEMENT + "\n\ndef _snapshot_dir_entry",
        text,
        count=1,
    )
    if count != 1:
        raise RuntimeError(
            f"create_marker_no_replace_under_lock: expected one match, found {count}"
        )

    old_regex_block = '''    marker_re = re.compile(
        rf"^{re.escape(prefix)}_txn_(\\d{{6}})_"
        rf"([0-9a-f]{{8}}-[0-9a-f]{{4}}-4[0-9a-f]{{3}}-"
        rf"[89ab][0-9a-f]{{3}}-[0-9a-f]{{12}})\\.marker$"
    )
    manifest_names: list[tuple[int, str]] = []
    marker_names: list[str] = []
'''
    new_regex_block = '''    marker_re = re.compile(
        rf"^{re.escape(prefix)}_txn_(\\d{{6}})_"
        rf"([0-9a-f]{{8}}-[0-9a-f]{{4}}-4[0-9a-f]{{3}}-"
        rf"[89ab][0-9a-f]{{3}}-[0-9a-f]{{12}})\\.marker$"
    )
    marker_temp_re = re.compile(
        rf"^{re.escape(prefix)}_txn_(\\d{{6}})_"
        rf"([0-9a-f]{{8}}-[0-9a-f]{{4}}-4[0-9a-f]{{3}}-"
        rf"[89ab][0-9a-f]{{3}}-[0-9a-f]{{12}})"
        rf"\\.marker\\.tmp\\.[0-9a-f]{{32}}$"
    )
    manifest_names: list[tuple[int, str]] = []
    marker_names: list[str] = []
    marker_temp_names: list[str] = []
'''
    text = replace_once(
        text, old_regex_block, new_regex_block, "marker temp regex insertion"
    )

    old_scan_block = '''        marker_match = marker_re.fullmatch(name)
        if marker_match is not None:
            marker_names.append(name)
            continue
        if name.startswith(f"{prefix}_txn_") and name.endswith(".marker"):
            raise MarkerValidationError(f"non-canonical transaction marker filename: {name}")
'''
    new_scan_block = '''        marker_match = marker_re.fullmatch(name)
        if marker_match is not None:
            marker_names.append(name)
            continue
        marker_temp_match = marker_temp_re.fullmatch(name)
        if marker_temp_match is not None:
            marker_temp_names.append(name)
            continue
        if name.startswith(f"{prefix}_txn_") and name.endswith(".marker"):
            raise MarkerValidationError(f"non-canonical transaction marker filename: {name}")
        if name.startswith(f"{prefix}_txn_") and ".marker.tmp." in name:
            raise MarkerValidationError(
                f"non-canonical transaction marker temp filename: {name}"
            )
'''
    text = replace_once(
        text, old_scan_block, new_scan_block, "marker temp scan insertion"
    )

    old_active_block = '''    if active_markers:
        raise RecoveryRequiredError(
            f"transaction markers require recovery: {active_markers}"
        )
'''
    new_active_block = '''    if active_markers or marker_temp_names:
        raise RecoveryRequiredError(
            "transaction marker evidence requires recovery: "
            f"markers={active_markers} temps={sorted(marker_temp_names)}"
        )
'''
    text = replace_once(
        text, old_active_block, new_active_block, "marker temp blocking"
    )

    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
