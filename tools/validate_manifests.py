#!/usr/bin/env python3
"""Validate rendered workload guardrails in a directory of Kubernetes YAML files."""

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

WORKLOADS = {"Deployment", "StatefulSet", "DaemonSet"}


def load_documents(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    documents = []
    for path in sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.yml")):
        if "kustomization.yaml" in path.name:
            continue
        try:
            for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
                if doc:
                    if not isinstance(doc, dict):
                        raise ValueError("document root must be a mapping")
                    documents.append((path, doc))
        except (OSError, yaml.YAMLError, ValueError) as error:
            raise ValueError(f"{path}: cannot parse YAML: {error}") from error
    return documents


def validate(root: Path) -> list[str]:
    """Return actionable findings. This complements schema and policy tools."""
    if not root.exists():
        return [f"{root}: path does not exist"]
    try:
        documents = load_documents(root)
    except ValueError as error:
        return [str(error)]
    if not documents:
        return [f"{root}: no Kubernetes YAML documents found"]

    findings: list[str] = []
    policies = [doc for _, doc in documents if doc.get("kind") == "NetworkPolicy"]
    workloads = [(path, doc) for path, doc in documents if doc.get("kind") in WORKLOADS]
    if not workloads:
        findings.append(f"{root}: no supported workload (Deployment/StatefulSet/DaemonSet) found")
    for path, workload in workloads:
        name = workload.get("metadata", {}).get("name", "<unnamed>")
        prefix = f"{path} ({name})"
        pod_template = workload.get("spec", {}).get("template", {})
        pod = pod_template.get("spec", {})
        pod_labels = pod_template.get("metadata", {}).get("labels", {})
        matching_policies = [
            policy
            for policy in policies
            if all(
                pod_labels.get(key) == value
                for key, value in policy.get("spec", {})
                .get("podSelector", {})
                .get("matchLabels", {})
                .items()
            )
        ]
        if not matching_policies:
            findings.append(f"{prefix}: no NetworkPolicy selects this workload")
        elif not any(
            "Ingress" in policy.get("spec", {}).get("policyTypes", [])
            for policy in matching_policies
        ):
            findings.append(f"{prefix}: no selecting NetworkPolicy enforces ingress policy")
        pod_security = pod.get("securityContext", {})
        if pod_security.get("runAsNonRoot") is not True:
            findings.append(f"{prefix}: pod securityContext must set runAsNonRoot: true")
        if pod_security.get("runAsUser") == 0:
            findings.append(f"{prefix}: pod securityContext must not run as UID 0")
        if pod.get("automountServiceAccountToken") is not False:
            findings.append(
                f"{prefix}: set automountServiceAccountToken: false when API access is unused"
            )
        containers = pod.get("containers", [])
        if not containers:
            findings.append(f"{prefix}: no containers declared")
        for container in containers:
            label = f"{prefix}, container {container.get('name', '<unnamed>')}"
            security = container.get("securityContext", {})
            if security.get("runAsUser") == 0:
                findings.append(f"{label}: container securityContext must not run as UID 0")
            if security.get("allowPrivilegeEscalation") is not False:
                findings.append(f"{label}: set allowPrivilegeEscalation: false")
            if security.get("privileged") is True:
                findings.append(f"{label}: privileged containers are forbidden")
            if security.get("readOnlyRootFilesystem") is not True:
                findings.append(f"{label}: set readOnlyRootFilesystem: true")
            dropped = security.get("capabilities", {}).get("drop", [])
            if "ALL" not in dropped:
                findings.append(f"{label}: drop ALL Linux capabilities")
            added = security.get("capabilities", {}).get("add", [])
            if added:
                findings.append(f"{label}: remove added Linux capabilities: {', '.join(added)}")
            resources = container.get("resources", {})
            for limit in ("requests", "limits"):
                cpu = resources.get(limit, {}).get("cpu")
                memory = resources.get(limit, {}).get("memory")
                if not cpu or not memory:
                    findings.append(f"{label}: define CPU and memory {limit}")
            for probe in ("livenessProbe", "readinessProbe"):
                if not container.get(probe):
                    findings.append(f"{label}: {probe} is required")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path", nargs="?", type=Path, default=Path("k8s"), help="YAML root (default: k8s)"
    )
    args = parser.parse_args(argv)
    findings = validate(args.path)
    if findings:
        print(f"FAIL: {len(findings)} manifest guardrail finding(s)")
        for finding in findings:
            print(f" - {finding}")
        return 1
    print(f"PASS: workload security guardrails satisfied under {args.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
