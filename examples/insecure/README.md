# Deliberately insecure example

This manifest is an isolated negative test fixture. It is not referenced by any Kustomize overlay
and must never be applied to a cluster. Run `python tools/validate_manifests.py examples/insecure`
to see the guardrail report non-root, privilege escalation, missing probes/resources, and missing
NetworkPolicy findings.
