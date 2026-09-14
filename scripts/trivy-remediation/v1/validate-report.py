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
FIELDS = (
    "VulnerabilityID",
    "PkgName",
    "InstalledVersion",
    "FixedVersion",
    "Severity",
    "Target",
    "Class",
    "Type",
)


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def project(report: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(report, dict) or not isinstance(report.get("Results"), list):
        fail("invalid Trivy report")

    results: list[dict[str, Any]] = []
    for result in report["Results"]:
        if not isinstance(result, dict):
            continue
        vulnerabilities: list[dict[str, Any]] = []
        for vulnerability in result.get("Vulnerabilities") or []:
            if (
                not isinstance(vulnerability, dict)
                or vulnerability.get("Severity") not in SEVERITIES
            ):
                continue
            vulnerabilities.append(
                {field: vulnerability.get(field) for field in FIELDS}
            )
        if vulnerabilities:
            results.append(
                {
                    "Target": result.get("Target"),
                    "Class": result.get("Class"),
                    "Type": result.get("Type"),
                    "Vulnerabilities": vulnerabilities,
                }
            )

    if sum(len(result["Vulnerabilities"]) for result in results) > MAX_FINDINGS:
        fail("too many vulnerability findings")
    return {"Results": results}


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
        for result in projected["Results"]:
            for vulnerability in result["Vulnerabilities"]:
                markers.append(
                    "trivy-remediation:"
                    f"{vulnerability.get('VulnerabilityID') or ''}|"
                    f"{vulnerability.get('PkgName') or ''}|"
                    f"{vulnerability.get('Target') or result.get('Target') or ''}|"
                    f"{vulnerability.get('FixedVersion') or ''}"
                )
        Path(sys.argv[3]).write_text(
            "\n".join(markers) + ("\n" if markers else ""), encoding="utf-8"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
