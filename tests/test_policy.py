from pathlib import Path

from app.approvals.policy import ApprovalMode, ApprovalPolicy


def test_policy_defaults_to_allow(tmp_path: Path) -> None:
    policy = ApprovalPolicy(tmp_path / "missing.yaml")

    assert policy.mode_for("unknown.tool") == ApprovalMode.ALLOW


def test_policy_reads_and_writes_modes(tmp_path: Path) -> None:
    path = tmp_path / "approvals.yaml"
    path.write_text(
        "version: 1\ndefault: require_approval\ntools:\n  memory.recall:\n    mode: allow\n",
        encoding="utf-8",
    )
    policy = ApprovalPolicy(path)

    assert policy.is_allowed("memory.recall")

    policy.set_mode("shell.run", ApprovalMode.DENY)
    reloaded = ApprovalPolicy(path)

    assert reloaded.is_denied("shell.run")
