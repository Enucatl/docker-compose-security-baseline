#!/usr/bin/env bash
set -euo pipefail
umask 022
root=$(cd "$(dirname "$0")/../.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
report="$tmp/report.json"

cat > "$report" <<'JSON'
{"Results":[{"Target":"debian","Class":"os-pkgs","Type":"debian","Secret":"must not pass","Vulnerabilities":[{"VulnerabilityID":"CVE-TEST","PkgName":"libtest","InstalledVersion":"1","FixedVersion":"2","Severity":"CRITICAL","Secret":"drop"}]}]}
JSON
"$root/scripts/trivy-remediation/v1/validate-report.sh" "$report" "$tmp/projected.json" "$tmp/markers"
[[ $(jq -r '.Results[0].Vulnerabilities[0].VulnerabilityID' "$tmp/projected.json") == CVE-TEST ]]
! jq -e '.. | objects | has("Secret")' "$tmp/projected.json" >/dev/null
grep -q '^trivy-remediation:CVE-TEST|libtest|debian|2$' "$tmp/markers"
printf '{malformed\n' > "$tmp/malformed.json"
if "$root/scripts/trivy-remediation/v1/validate-report.sh" "$tmp/malformed.json" "$tmp/bad"; then exit 1; fi

jq '.Results[0].Vulnerabilities as $v | .Results[0].Vulnerabilities = [range(0;101) | $v[0]]' "$report" > "$tmp/too-many-report.json"
if "$root/scripts/trivy-remediation/v1/validate-report.sh" "$tmp/too-many-report.json" "$tmp/too-many"; then exit 1; fi

cd "$tmp"; git init -q; git config user.email test@example.invalid; git config user.name test
git add .; git commit -qm base
printf 'safe\n' > safe.txt; git add -N safe.txt
patch="$tmp/../trivy-remediation.patch"
"$root/scripts/trivy-remediation/v1/package-patch.sh" "$patch"
[[ -s "$patch" ]]
"$root/scripts/trivy-remediation/v1/validate-diff.sh" "$patch"
mkdir applied; cd applied; git init -q; git config user.email test@example.invalid; git config user.name test
printf 'base\n' > base.txt; git add .; git commit -qm base
git apply "$patch"
grep -q safe safe.txt
echo 'trivy remediation fixture tests passed'
