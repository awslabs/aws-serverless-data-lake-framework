#!/usr/bin/env bash
set -ex

# python
black --check .
ruff check .
# pylint $(git ls-files --exclude-standard '*.py') # pylint is disabled for now
trivy fs --security-checks vuln .

# shell
find . -not \( -path ./sdlf-utils -prune \) -type f \( -name '*.sh' -o -name '*.bash' -o -name '*.ksh' \) -print0 \
| xargs -0 shellcheck -x --format gcc

# cloudformation
find . -not \( -path ./sdlf-utils -prune \) -type f -name '*.yaml' -print0 \
| xargs -0 cfn-lint
find . -not \( -path ./sdlf-utils -prune \) -type f -name '*.yaml' -print0 \
| xargs -0 -L 1 cfn_nag_scan --deny-list-path .cfn-nag-deny-list.yml --input-path
