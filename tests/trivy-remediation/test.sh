#!/usr/bin/env bash
set -euo pipefail
umask 022
root=$(cd "$(dirname "$0")/../.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
report="$tmp/report.json"

cat > "$report" <<'JSON'
{"Results":[{"Target":"debian","Class":"os-pkgs","Type":"debian","Secret":"must not pass","Vulnerabilities":[{"VulnerabilityID":"CVE-TEST","PkgName":"libtest","InstalledVersion":"1","FixedVersion":"2, 3","Severity":"CRITICAL","Secret":"drop"},{"VulnerabilityID":"CVE-UNFIXED","PkgName":"libunfixed","InstalledVersion":"1","Severity":"HIGH"}]}]}
JSON
"$root/scripts/trivy-remediation/v1/validate-report.py" "$report" "$tmp/projected.json" "$tmp/markers"
[[ $(jq -r '.findings[0].cve' "$tmp/projected.json") == CVE-TEST ]]
[[ $(jq -r '.findings[0].fixed[0]' "$tmp/projected.json") == 2 ]]
[[ $(jq -r '.findings[0].fixed[1]' "$tmp/projected.json") == 3 ]]
[[ $(jq -r '.findings | length' "$tmp/projected.json") == 1 ]]
! jq -e '.. | objects | has("Secret")' "$tmp/projected.json" >/dev/null
grep -q '^trivy-remediation:CVE-TEST|libtest|debian|2,3$' "$tmp/markers"
"$root/scripts/trivy-remediation/v1/validate-report.py" "$tmp/projected.json" "$tmp/revalidated.json" "$tmp/revalidated-markers"
cmp "$tmp/projected.json" "$tmp/revalidated.json"
cmp "$tmp/markers" "$tmp/revalidated-markers"
printf '%s\n' '{"findings":[{"target":"debian","type":"os","cve":"CVE-TEST","package":"libtest","installed":"1","fixed":["2"],"severity":"CRITICAL","unexpected":"drop"}]}' > "$tmp/untrusted-compact.json"
"$root/scripts/trivy-remediation/v1/validate-report.py" "$tmp/untrusted-compact.json" "$tmp/trusted-compact.json"
! jq -e '.findings[0] | has("unexpected")' "$tmp/trusted-compact.json" >/dev/null
printf '{malformed\n' > "$tmp/malformed.json"
if "$root/scripts/trivy-remediation/v1/validate-report.py" "$tmp/malformed.json" "$tmp/bad"; then exit 1; fi

jq '.Results[0].Vulnerabilities as $v | .Results[0].Vulnerabilities = [range(0;101) | $v[0]]' "$report" > "$tmp/too-many-report.json"
if "$root/scripts/trivy-remediation/v1/validate-report.py" "$tmp/too-many-report.json" "$tmp/too-many"; then exit 1; fi

cd "$tmp"; git init -q; git config user.email test@example.invalid; git config user.name test
git add .; git commit -qm base
printf 'safe\n' > safe.txt; git add -N safe.txt
patch="$tmp/../trivy-remediation.patch"
"$root/scripts/trivy-remediation/v1/package-patch.sh" "$patch"
[[ -s "$patch" ]]
"$root/scripts/trivy-remediation/v1/validate-diff.py" "$patch"
mkdir applied; cd applied; git init -q; git config user.email test@example.invalid; git config user.name test
printf 'base\n' > base.txt; git add .; git commit -qm base
git apply "$patch"
grep -q safe safe.txt
printf '\0binary\n' > binary.bin; git add -N binary.bin
if "$root/scripts/trivy-remediation/v1/package-patch.sh" "$tmp/../binary.patch"; then exit 1; fi
echo 'trivy remediation fixture tests passed'
