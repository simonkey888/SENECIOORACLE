# H-011 Phase II-A hostile audit

Status: implementation and crash validation in progress.

Scope is limited to `publish_raw_scan()` and its marker-creation dependency at publisher base SHA `e26c79aeb97973bdb1d700c1edb8b47542b15153`.

Confirmed pre-test findings:

1. The marker temp source is linked without explicitly disabling symlink following.
2. The canonical marker is not verified by exact bytes and inode identity before caller ownership is consumed.
3. A canonical marker-temp residue without a final marker is ignored by manifest-chain inspection, permitting a subsequent publication instead of requiring recovery.

The branch contains a one-shot exact patcher and a real `os._exit()` crash matrix. The patch is committed only after the Linux audit suite passes.
