#!/usr/bin/env python3
"""Validate the narrow patch surface allowed by Trivy remediation."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from fnmatch import fnmatchcase
from pathlib import Path

MAX_FILES = 20
MAX_BYTES = 131_072
PROHIBITED_PATTERNS = (
    ".git*",
    "*trivy*config*",
    "*trivy*ignore*",
    "*security-policy*",
    "*SECURITY*",
    "*security.yml",
    "*security.yaml",
)


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def git_paths(*args: str) -> set[str]:
    try:
        output = subprocess.check_output(["git", *args], stderr=subprocess.STDOUT)
    except (OSError, subprocess.CalledProcessError) as error:
        message = (
            error.output.decode(errors="replace")
            if isinstance(error, subprocess.CalledProcessError)
            else str(error)
        )
        fail(message.strip() or "git command failed")
    return {os.fsdecode(path) for path in output.split(b"\0") if path}


def prohibited(path: str) -> bool:
    return (
        path.startswith(("/", ".github/", ".agents/"))
        or ".." in path
        or any(fnmatchcase(path, pattern) for pattern in PROHIBITED_PATTERNS)
    )


def validate_worktree(paths: set[str]) -> None:
    if len(paths) > MAX_FILES:
        fail("patch changes too many files")
    for path in sorted(paths):
        if prohibited(path):
            fail(f"prohibited path: {path}")
        target = Path(path)
        if target.is_symlink():
            fail(f"symlink is not allowed: {path}")
        try:
            metadata = target.lstat()
        except OSError as error:
            fail(f"cannot stat path: {path}: {error}")
        if not stat.S_ISREG(metadata.st_mode):
            fail(f"special file is not allowed: {path}")
        if metadata.st_nlink != 1:
            fail(f"hard link is not allowed: {path}")
        if stat.S_IMODE(metadata.st_mode) not in (0o644, 0o755):
            fail(f"invalid mode: {path}")


def validate_patch(path: Path) -> None:
    try:
        patch = path.read_bytes()
    except OSError as error:
        fail(str(error))
    if not patch:
        fail("empty patch")
    if len(patch) > MAX_BYTES:
        fail("patch is too large")

    paths = re.findall(rb"^diff --git a/(.*) b/.*$", patch, re.MULTILINE)
    if len(paths) > MAX_FILES:
        fail("patch changes too many files")
    for patch_path in paths:
        decoded_path = os.fsdecode(patch_path)
        if prohibited(decoded_path):
            fail(f"prohibited patch path: {decoded_path}")
    if re.search(rb"^(new|old) file mode (120000|160000)", patch, re.MULTILINE):
        fail("symlink or submodule mode denied")


def main() -> int:
    validate_worktree(
        git_paths(
            "diff", "--name-only", "-z", "--diff-filter=ACDMRTUXB", "HEAD", "--", "."
        )
        | git_paths("ls-files", "--others", "--exclude-standard", "-z")
    )
    patch_name = os.environ.get("PATCH_PATH") or (
        sys.argv[1] if len(sys.argv) > 1 else ""
    )
    if patch_name:
        validate_patch(Path(patch_name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
