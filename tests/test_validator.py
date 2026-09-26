from pathlib import Path

from tools.validate_manifests import validate


def test_base_kustomize_manifests_have_guardrails():
    assert validate(Path("k8s/base")) == []


def test_insecure_fixture_fails_with_expected_findings():
    findings = validate(Path("examples/insecure"))
    report = "\n".join(findings)
    assert "runAsNonRoot" in report
    assert "privileged containers" in report
    assert "UID 0" in report
    assert "added Linux capabilities" in report
    assert "readinessProbe" in report
    assert "no NetworkPolicy selects this workload" in report


def test_missing_path_fails():
    assert "path does not exist" in validate(Path("missing-manifests"))[0]
