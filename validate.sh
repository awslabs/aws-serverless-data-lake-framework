#!/usr/bin/env bash
set -ex

# python
ruff format --check .
ruff check .
# pylint $(git ls-files --exclude-standard '*.py') # pylint is disabled for now
trivy fs --scanners vuln .

# shell
find . -type f \( -name '*.sh' -o -name '*.bash' -o -name '*.ksh' \) -print0 \
| xargs -0 shellcheck -x --format gcc

# cloudformation
find . -type f -name '*.yaml' -print0 \
| xargs -0 cfn-lint
## unfortunately cfn_nag doesn't support fn::foreach so we exclude files using it: https://github.com/stelligent/cfn_nag/issues/621
find . -not \( -type f -name 'template-glue-job.yaml' -o -type f -name 'template-lambda-layer.yaml' \) -type f -name '*.yaml' -print0 \
| xargs -0 -L 1 cfn_nag_scan --fail-on-warnings --ignore-fatal --deny-list-path .cfn-nag-deny-list.yml --input-path
