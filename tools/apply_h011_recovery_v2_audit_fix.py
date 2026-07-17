from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"unexpected source for {label}: count={text.count(old)}")
    return text.replace(old, new, 1)


recovery_path = Path("polymarket/h011_v3_raw_recovery.py")
recovery = recovery_path.read_text(encoding="utf-8")

recovery = replace_once(
    recovery,
    '''    raw, _ = _read_regular(root_fd, name)\n    marker = rt.parse_marker(raw)\n    rt.validate_marker(marker, policy)\n    expected = rt.marker_filename(\n''',
    '''    raw, _ = _read_regular(root_fd, name)\n    marker = rt.parse_marker(raw)\n    rt.validate_marker(marker, policy)\n    if rt.canonical_json_bytes(marker) != raw:\n        raise rt.MarkerValidationError(\n            f"marker {name} is valid but not canonically encoded"\n        )\n    expected = rt.marker_filename(\n''',
    "canonical marker loading",
)

recovery = replace_once(
    recovery,
    '''    return sorted(valid), sorted(malformed)\n\n\n''',
    '''    return sorted(valid), sorted(malformed)\n\n\ndef _marker_temp_owners(\n    *, root_fd: int, prefix: str\n) -> tuple[dict[str, list[str]], list[str]]:\n    marker_pattern = (\n        rf"{re.escape(prefix)}_txn_(\\d{{6}})_"\n        rf"[0-9a-f]{{8}}-[0-9a-f]{{4}}-4[0-9a-f]{{3}}-"\n        rf"[89ab][0-9a-f]{{3}}-[0-9a-f]{{12}}\\.marker"\n    )\n    temp_re = re.compile(\n        rf"^(?P<owner>{marker_pattern})\\.tmp\\.[0-9a-f]+$"\n    )\n    owners: dict[str, list[str]] = {}\n    malformed: list[str] = []\n    for name in os.listdir(root_fd):\n        if not (\n            name.startswith(f"{prefix}_txn_")\n            and ".marker.tmp." in name\n        ):\n            continue\n        match = temp_re.fullmatch(name)\n        if match is None:\n            malformed.append(name)\n            continue\n        owners.setdefault(match.group("owner"), []).append(name)\n    return (\n        {owner: sorted(names) for owner, names in sorted(owners.items())},\n        sorted(malformed),\n    )\n\n\n''',
    "marker temp ownership helper",
)

recovery = replace_once(
    recovery,
    '''        marker_names, malformed = _canonical_marker_names(\n            root_fd=root_fd, prefix=policy.manifest_prefix\n        )\n        if malformed:\n            raise RecoveryBlockedError(\n                f"non-canonical transaction markers: {malformed}",\n                failure_stage=stage,\n                marker_filename=None,\n                filesystem_snapshot={\n                    "malformed_markers": malformed,\n                    "root_names": sorted(os.listdir(root_fd)),\n                },\n            )\n        if not marker_names:\n            # A previous recovery attempt may have unlinked its marker before\n            # confirming the directory fsync. Fsync makes no-marker durable.\n            os.fsync(root_fd)\n            return RecoveryResult(\n                status="NO_RECOVERY_NEEDED",\n                marker_filename=None,\n                recovered_from_status=None,\n                final_status=None,\n                manifest_entry=None,\n            )\n        if len(marker_names) != 1:\n            raise RecoveryBlockedError(\n                f"expected exactly one transaction marker, found {marker_names}",\n                failure_stage=stage,\n                marker_filename=None,\n                filesystem_snapshot={\n                    "markers": marker_names,\n                    "root_names": sorted(os.listdir(root_fd)),\n                },\n            )\n\n        marker_name = marker_names[0]\n''',
    '''        marker_names, malformed_markers = _canonical_marker_names(\n            root_fd=root_fd, prefix=policy.manifest_prefix\n        )\n        marker_temp_owners, malformed_temps = _marker_temp_owners(\n            root_fd=root_fd, prefix=policy.manifest_prefix\n        )\n        if malformed_markers or malformed_temps:\n            raise RecoveryBlockedError(\n                "non-canonical transaction marker evidence: "\n                f"markers={malformed_markers} temps={malformed_temps}",\n                failure_stage=stage,\n                marker_filename=None,\n                filesystem_snapshot={\n                    "malformed_markers": malformed_markers,\n                    "malformed_marker_temps": malformed_temps,\n                    "root_names": sorted(os.listdir(root_fd)),\n                },\n            )\n        if not marker_names:\n            if marker_temp_owners:\n                raise RecoveryBlockedError(\n                    "orphan durable marker-temp evidence requires explicit "\n                    f"recovery: {marker_temp_owners}",\n                    failure_stage=stage,\n                    marker_filename=None,\n                    filesystem_snapshot={\n                        "orphan_marker_temps": marker_temp_owners,\n                        "root_names": sorted(os.listdir(root_fd)),\n                    },\n                )\n            # A previous recovery attempt may have unlinked its marker before\n            # confirming the directory fsync. Fsync makes no-marker durable.\n            os.fsync(root_fd)\n            return RecoveryResult(\n                status="NO_RECOVERY_NEEDED",\n                marker_filename=None,\n                recovered_from_status=None,\n                final_status=None,\n                manifest_entry=None,\n            )\n        if len(marker_names) != 1:\n            raise RecoveryBlockedError(\n                f"expected exactly one transaction marker, found {marker_names}",\n                failure_stage=stage,\n                marker_filename=None,\n                filesystem_snapshot={\n                    "markers": marker_names,\n                    "marker_temps": marker_temp_owners,\n                    "root_names": sorted(os.listdir(root_fd)),\n                },\n            )\n\n        marker_name = marker_names[0]\n        foreign_temp_owners = sorted(\n            owner for owner in marker_temp_owners if owner != marker_name\n        )\n        if foreign_temp_owners:\n            raise RecoveryBlockedError(\n                "marker-temp evidence belongs to another transaction: "\n                f"{foreign_temp_owners}",\n                failure_stage=stage,\n                marker_filename=marker_name,\n                filesystem_snapshot={\n                    "marker": marker_name,\n                    "marker_temps": marker_temp_owners,\n                    "root_names": sorted(os.listdir(root_fd)),\n                },\n            )\n''',
    "discovery marker-temp handling",
)

recovery = replace_once(
    recovery,
    '''        if current["status"] != "COMMITTED" or current["resolution"] != "COMMITTED":\n            raise RawTransactionRecoveryError(\n                "marker is not durably COMMITTED before final cleanup"\n            )\n        if current["candidate_manifest"] != marker["candidate_manifest"]:\n            raise RawTransactionRecoveryError(\n                "marker candidate changed before final cleanup"\n            )\n''',
    '''        if marker["status"] != "COMMITTED" or marker["resolution"] != "COMMITTED":\n            raise RawTransactionRecoveryError(\n                "in-memory marker is not durably COMMITTED before final cleanup"\n            )\n        if current != marker:\n            raise RawTransactionRecoveryError(\n                "marker changed before final cleanup"\n            )\n''',
    "final marker identity comparison",
)
recovery_path.write_text(recovery, encoding="utf-8")


tests_path = Path("tests/h011_v3/test_h011_v3_recover_raw_transaction.py")
tests = tests_path.read_text(encoding="utf-8")
tests = replace_once(
    tests,
    "import sys\nfrom pathlib import Path\n",
    "import sys\nimport uuid\nfrom pathlib import Path\n",
    "test uuid import",
)

additions = r'''


def test_orphan_marker_temp_blocks_instead_of_reporting_noop(
    raw_dir: Path,
    policy: MarkerValidationPolicy,
):
    orphan = raw_dir / (
        "manifest_txn_000000_11111111-1111-4111-8111-111111111111"
        ".marker.tmp.deadbeef"
    )
    orphan.write_bytes(b"orphan-marker-temp")
    orphan.chmod(0o444)

    with pytest.raises(RecoveryBlockedError) as raised:
        _recover(raw_dir, policy)

    assert raised.value.failure_stage == "R0_DISCOVERY"
    assert raised.value.recoverable is False
    assert orphan.read_bytes() == b"orphan-marker-temp"


def test_marker_replacement_during_cleanup_is_not_deleted(
    raw_dir: Path,
    policy: MarkerValidationPolicy,
    monkeypatch,
):
    _crash(
        raw_dir,
        policy,
        rt.FAULT_PUBLISH_AFTER_STAGED_MARKER,
        scan_id="marker-replacement",
    )
    marker_path = _marker_paths(raw_dir)[0]
    original = rt.parse_marker(marker_path.read_bytes())
    real_cleanup = recovery._cleanup_owned_temps

    def replacing_cleanup(*, root_fd, marker_name, marker):
        removed = real_cleanup(
            root_fd=root_fd,
            marker_name=marker_name,
            marker=marker,
        )
        replacement = rt.parse_marker(marker_path.read_bytes())
        replacement["ownership_token"] = str(uuid.uuid4())
        replacement_bytes = rt.prepare_validated_marker_bytes(
            replacement,
            policy,
        )
        marker_path.chmod(0o644)
        marker_path.write_bytes(replacement_bytes)
        marker_path.chmod(0o444)
        return removed

    monkeypatch.setattr(recovery, "_cleanup_owned_temps", replacing_cleanup)

    with pytest.raises(RecoveryBlockedError) as raised:
        _recover(raw_dir, policy)

    assert raised.value.failure_stage == "R8_MARKER_CLEANUP"
    assert marker_path.is_file()
    current = rt.parse_marker(marker_path.read_bytes())
    assert current["ownership_token"] != original["ownership_token"]
'''
if "test_orphan_marker_temp_blocks_instead_of_reporting_noop" in tests:
    raise SystemExit("audit regression tests already present")
tests_path.write_text(tests.rstrip() + additions + "\n", encoding="utf-8")
