#!/usr/bin/env bash
# Checks the alert rules and runs their unit tests with promtool.
# Needs promtool and python3 with PyYAML.
set -euo pipefail

if ! command -v promtool > /dev/null; then
  echo "promtool is not installed or not on the PATH."
  exit 1
fi

cd "$(dirname "$0")/.."
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# Pull the rule groups out of the PrometheusRule objects.
for file in monitoring/config/rules-*.yaml; do
  python3 - "$file" "$work/$(basename "$file")" <<'PY'
import sys
import yaml

doc = yaml.safe_load(open(sys.argv[1]))
yaml.safe_dump({"groups": doc["spec"]["groups"]}, open(sys.argv[2], "w"))
PY
done

promtool check rules "$work"/rules-*.yaml

# promtool expects the rule files next to the tests.
cp test/rules/*-test.yaml "$work"/
cd "$work"
promtool test rules ./*-test.yaml
