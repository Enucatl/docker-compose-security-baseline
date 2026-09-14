#!/usr/bin/env python3
"""Project safe Trivy findings for the remediation agent."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

MAX_FINDINGS = 100
MAX_OUTPUT_BYTES = 262_144
SEVERITIES = {"HIGH", "CRITICAL"}
COMPACT_FIELDS = (
    "target",
    "type",
    "cve",
    "package",
    "installed",
    "fixed",
    "severity",
)


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def fixed_versions(value: Any) -> list[str]:
    values = value if isinstance(value, list) else text(value).split(",")
    return [
        version.strip()
        for version in values
        if isinstance(version, str) and version.strip()
    ]


def compact_finding(
    vulnerability: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any] | None:
    if vulnerability.get("Severity") not in SEVERITIES:
        return None
    fixed = fixed_versions(vulnerability.get("FixedVersion"))
    if not fixed:
        return None
    return {
        "target": text(vulnerability.get("Target") or result.get("Target")),
        "type": text(vulnerability.get("Type") or result.get("Type")),
        "cve": text(vulnerability.get("VulnerabilityID")),
        "package": text(vulnerability.get("PkgName")),
        "installed": text(vulnerability.get("InstalledVersion")),
        "fixed": fixed,
        "severity": text(vulnerability.get("Severity")),
    }


def project_full(report: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(report, dict) or not isinstance(report.get("Results"), list):
        fail("invalid Trivy report")

    findings: list[dict[str, Any]] = []
    for result in report["Results"]:
        if not isinstance(result, dict):
            continue
        vulnerabilities = result.get("Vulnerabilities")
        if not isinstance(vulnerabilities, list):
            continue
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict):
                continue
            finding = compact_finding(vulnerability, result)
            if finding is not None:
                findings.append(finding)

    return compact_findings(findings)


def compact_findings(findings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    if len(findings) > MAX_FINDINGS:
        fail("too many vulnerability findings")
    return {"findings": findings}


def validate_compact(report: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(report, dict) or not isinstance(report.get("findings"), list):
        fail("invalid compact Trivy report")

    findings: list[dict[str, Any]] = []
    for finding in report["findings"]:
        if not isinstance(finding, dict) or any(
            field not in finding for field in COMPACT_FIELDS
        ):
            fail("invalid compact Trivy finding")
        if any(
            not isinstance(finding[field], str)
            for field in COMPACT_FIELDS
            if field != "fixed"
        ):
            fail("invalid compact Trivy finding")
        if finding["severity"] not in SEVERITIES or not isinstance(
            finding["fixed"], list
        ):
            fail("invalid compact Trivy finding")
        fixed = fixed_versions(finding["fixed"])
        if not fixed or len(fixed) != len(finding["fixed"]):
            fail("invalid compact Trivy finding")
        findings.append(
            {
                field: fixed if field == "fixed" else finding[field]
                for field in COMPACT_FIELDS
            }
        )

    return compact_findings(findings)


def project(report: Any) -> dict[str, list[dict[str, Any]]]:
    if isinstance(report, dict) and "findings" in report:
        return validate_compact(report)
    return project_full(report)


def write_atomically(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(data)
        os.replace(temporary_path, path)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def main() -> int:
    if len(sys.argv) not in (3, 4):
        fail("usage: validate-report.py INPUT OUTPUT [MARKERS]")

    input_path, output_path = map(Path, sys.argv[1:3])
    try:
        if not input_path.is_file() or input_path.stat().st_size == 0:
            fail("missing Trivy report")
        with input_path.open(encoding="utf-8") as stream:
            projected = project(json.load(stream))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"invalid Trivy report: {error}")

    data = (
        json.dumps(projected, ensure_ascii=True, separators=(",", ":")) + "\n"
    ).encode()
    if len(data) > MAX_OUTPUT_BYTES:
        fail("projected report exceeds 256 KiB")
    write_atomically(output_path, data)

    if len(sys.argv) == 4:
        markers: list[str] = []
        for finding in projected["findings"]:
            markers.append(
                "trivy-remediation:"
                f"{finding['cve']}|"
                f"{finding['package']}|"
                f"{finding['target']}|"
                f"{','.join(finding['fixed'])}"
            )
        Path(sys.argv[3]).write_text(
            "\n".join(markers) + ("\n" if markers else ""), encoding="utf-8"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
