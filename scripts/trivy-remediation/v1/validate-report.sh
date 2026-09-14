#!/usr/bin/env bash
set -euo pipefail

input=${1:?input report required}
output=${2:?output report required}
marker=${3:?policy marker required}
markers=${4:-}

[[ -s "$input" ]] || { echo "missing Trivy report" >&2; exit 1; }
mkdir -p "$(dirname -- "$output")"

jq -e 'type == "object" and (.Results | type == "array")' "$input" >/dev/null

# Deliberately construct a new document: scanner metadata, embedded messages,
# secrets, and arbitrary future fields never reach the coding agent.
jq -c '
  {Results: [ .Results[]? |
    {Target,Class,Type,
     Vulnerabilities: [ .Vulnerabilities[]? |
       select(.Severity == "HIGH" or .Severity == "CRITICAL") |
       {VulnerabilityID,PkgName,InstalledVersion,FixedVersion,Severity,Target,Class,Type}
     ]
    }
  ]} |
  .Results |= map(select((.Vulnerabilities | length) > 0)) |
  (.Results | map(.Vulnerabilities[]) | length) as $count |
  if $count > 100 then error("too many vulnerability findings") else . end
' "$input" > "$output.tmp"
[[ $(wc -c < "$output.tmp") -le 262144 ]] || { rm -f "$output.tmp"; echo "projected report exceeds 256 KiB" >&2; exit 1; }
mv -- "$output.tmp" "$output"
printf 'true\n' > "$marker"
if [[ -n "$markers" ]]; then
  jq -r '.Results[] as $result | $result.Vulnerabilities[]? | "trivy-remediation:" + (.VulnerabilityID // "") + "|" + (.PkgName // "") + "|" + (.Target // $result.Target // "") + "|" + (.FixedVersion // "")' "$output" > "$markers"
fi
