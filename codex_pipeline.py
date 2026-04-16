from __future__ import annotations

import subprocess
from pathlib import Path

import click


def ensure_workspace(repo_root: Path) -> None:
    (repo_root / "issues").mkdir(exist_ok=True)
    (repo_root / "validated").mkdir(exist_ok=True)
    (repo_root / "rejected").mkdir(exist_ok=True)


def repo_relative(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def abs_path(path: Path) -> str:
    return str(path.resolve())


def codex_cmd(repo_root: Path) -> list[str]:
    return [
        "npx",
        "@openai/codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--cd",
        str(repo_root),
    ]


def run_codex(
    repo_root: Path, prompt: str, timeout: int = 120
) -> subprocess.CompletedProcess[str]:
    """Run codex CLI non-interactively with a prompt."""
    click.echo(f"🤖 Running codex: {prompt[:80]}...")
    try:
        result = subprocess.run(
            codex_cmd(repo_root) + [prompt],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=repo_root,
        )
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(
            f"Codex failed: {exc.stderr.strip() or exc.stdout.strip() or exc}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise click.ClickException(
            "Codex timed out. Increase the timeout or simplify the prompt."
        ) from exc

    stdout = result.stdout.strip()
    if stdout:
        click.echo(stdout)

    stderr = result.stderr.strip()
    if stderr:
        click.echo(stderr, err=True)

    return result


def fetch_github_issue(repo_root: Path, owner: str, repo: str, num: int) -> None:
    """Download issue body using GitHub CLI."""
    review_file = repo_root / "review.md"
    cmd = [
        "gh",
        "issue",
        "view",
        str(num),
        "-R",
        f"{owner}/{repo}",
        "--json",
        "body",
        "-q",
        ".body",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(
            f"Failed to fetch issue via gh: {exc.stderr.strip() or exc.stdout.strip() or exc}"
        ) from exc

    review_file.write_text(result.stdout)
    click.echo(f"✅ Saved review to {repo_relative(review_file, repo_root)}")


def build_split_prompt(repo_root: Path) -> str:
    review_file = repo_root / "review.md"
    issues_dir = repo_root / "issues"
    return (
        f"Read '{abs_path(review_file)}' as a review input.\n"
        f"Extract every concrete, testable candidate finding that the review actually supports and "
        f"that could plausibly affect security, reliability, availability, data integrity, abuse "
        f"resistance, incident response, or operational safety.\n"
        f"Do not require the finding to be a proven security issue at this split stage; later validation "
        f"will decide whether it is VALID, INVALID, or UNVERIFIABLE as a security shortcoming.\n"
        f"Do not invent new risks, do not include praise, and do not include purely stylistic feedback.\n"
        f"Create one file per distinct shortcoming in '{abs_path(issues_dir)}/issue_1.md', "
        f"'{abs_path(issues_dir)}/issue_2.md', and so on.\n"
        f"Each file must contain:\n"
        f"# Title\n"
        f"## Candidate Claim\n"
        f"## Why this looks real\n"
        f"## Verification Target\n"
        f"## Severity (low/med/high/critical)\n"
        f"## Tags\n"
        f"The Candidate Claim should read like a concrete shortcoming, not a vague hypothesis.\n"
        f"If the review contains concrete observations such as blocking async I/O, swallowed errors, "
        f"race conditions, unbounded memory use, missing retries, missing rate limits, scattered "
        f"configuration, or missing observability, create issue files for them so they can be verified.\n"
        f"If the review contains no concrete, testable candidate findings, write no issue files and print "
        f"'NO_ACTIONABLE_ISSUES'.\n"
        f"Do not output to console otherwise."
    )


def step_split_issues(repo_root: Path) -> None:
    issues_dir = repo_root / "issues"
    rejected_dir = repo_root / "rejected"
    no_actionable_file = rejected_dir / "no_actionable_issues.md"

    for issue_file in issues_dir.glob("*.md"):
        issue_file.unlink()
    no_actionable_file.unlink(missing_ok=True)

    run_codex(repo_root, build_split_prompt(repo_root))

    if list(issues_dir.glob("*.md")):
        return

    no_actionable_file.write_text(
        "# No Actionable Issues\n\n"
        "## Status: INVALID\n\n"
        "## Confidence (0-100%)\n"
        "100\n\n"
        "## Evidence & Reasoning\n"
        "The review content did not yield any concrete, testable candidate findings that could be "
        "split into discrete verification inputs. No issue files were created.\n\n"
        "## Verification outcome\n"
        "No validated security work items were derived from the review.\n"
    )
    click.echo(
        f"ℹ️ No actionable issues found. Wrote {repo_relative(no_actionable_file, repo_root)}"
    )


def build_validation_prompt(repo_root: Path, issue_file: Path) -> str:
    validated_file = repo_root / "validated" / f"{issue_file.stem}_validated.md"
    rejected_file = repo_root / "rejected" / f"{issue_file.stem}_rejected.md"
    return (
        f"Read '{abs_path(issue_file)}'. Verify whether the described candidate finding is actually "
        f"present in the current codebase and whether it is a verified security shortcoming.\n"
        f"Inspect the repository and use concrete evidence from code, configuration, scripts, or docs.\n"
        f"Mark the report VALID only if the shortcoming is confirmed by direct evidence and you can "
        f"explain why it weakens the security baseline.\n"
        f"Mark INVALID if the concern is contradicted, already mitigated, or is not a security issue.\n"
        f"Mark UNVERIFIABLE only if reasonable inspection still leaves you without enough evidence.\n"
        f"If the result is VALID, write '{abs_path(validated_file)}' with:\n"
        f"# Title\n"
        f"## Status: VALID/INVALID/UNVERIFIABLE\n"
        f"## Confidence (0-100%)\n"
        f"## Evidence & Reasoning\n"
        f"## Verification outcome\n"
        f"The reasoning should answer: what exactly is broken, how do you know, and what would have "
        f"to change for the issue to be dismissed.\n"
        f"If the result is INVALID or UNVERIFIABLE, write '{abs_path(rejected_file)}' instead "
        f"with the same required sections and the matching status.\n"
        f"Print 'VALIDATED: {issue_file.stem}' when done."
    )


def step_validate_issues(repo_root: Path) -> None:
    issues_dir = repo_root / "issues"
    validated_dir = repo_root / "validated"
    rejected_dir = repo_root / "rejected"
    issue_files = sorted(issues_dir.glob("*.md"))
    if not issue_files:
        click.echo("⚠️ No issue files found. Skipping validation.")
        return

    for issue_file in issue_files:
        validated_file = validated_dir / f"{issue_file.stem}_validated.md"
        rejected_file = rejected_dir / f"{issue_file.stem}_rejected.md"
        validated_file.unlink(missing_ok=True)
        rejected_file.unlink(missing_ok=True)

        run_codex(
            repo_root, build_validation_prompt(repo_root, issue_file), timeout=180
        )
        if validated_file.exists() or rejected_file.exists():
            continue

        rejected_file.write_text(
            f"# {issue_file.stem.replace('_', ' ').title()}\n\n"
            f"## Status: UNVERIFIABLE\n\n"
            f"## Confidence (0-100%)\n"
            f"0\n\n"
            f"## Evidence & Reasoning\n"
            f"Codex did not emit a validation artifact for this issue, so the claim cannot be treated "
            f"as validated.\n\n"
            f"## Verification outcome\n"
            f"Rejected as a missing validation result.\n"
        )
        click.echo(
            f"ℹ️ Validation produced no file; wrote {repo_relative(rejected_file, repo_root)}"
        )


def build_plan_prompt(repo_root: Path, validated_files: list[Path]) -> str:
    validated_dir = repo_root / "validated"
    plan_file = validated_dir / "fix_plan.md"
    valid_list = (
        "\n".join(f"- {abs_path(path)}" for path in validated_files) or "- (none)"
    )
    return (
        f"Read the validated reports in '{abs_path(validated_dir)}'.\n"
        f"Confirmed reports:\n{valid_list}\n\n"
        f"Create '{abs_path(plan_file)}' with a prioritized remediation plan based only on "
        f"these validated findings.\n"
        f"Include:\n"
        f"- Phase 1: Critical fixes\n"
        f"- Phase 2: High priority\n"
        f"- Phase 3: Medium/Low\n"
        f"Each phase should list actionable tasks, estimated effort (S/M/L), and dependencies.\n"
        f"If there are no validated findings, write a short plan stating that no verified security "
        f"shortcomings were identified.\n"
        f"Write ONLY to '{abs_path(plan_file)}'. Print 'PLAN_COMPLETE' when done."
    )


def step_generate_plan(repo_root: Path) -> None:
    validated_dir = repo_root / "validated"
    validated_files = sorted(validated_dir.glob("*_validated.md"))
    if not validated_files:
        click.echo("⚠️ No validated files found. Generating a no-findings plan.")

    run_codex(repo_root, build_plan_prompt(repo_root, validated_files), timeout=180)


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("owner", type=str)
@click.argument("repo", type=str)
@click.argument("issue_number", type=int)
def main(owner: str, repo: str, issue_number: int) -> None:
    repo_root = Path.cwd().resolve()
    ensure_workspace(repo_root)

    click.echo("🌐 Fetching GitHub issue...")
    fetch_github_issue(repo_root, owner, repo, issue_number)

    click.echo("📦 Splitting review into issues...")
    step_split_issues(repo_root)

    click.echo("🔍 Validating issues against codebase...")
    step_validate_issues(repo_root)

    click.echo("📝 Generating fix plan...")
    step_generate_plan(repo_root)

    click.echo("✅ Pipeline complete!")


if __name__ == "__main__":
    main()
