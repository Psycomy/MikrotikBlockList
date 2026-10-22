#!/usr/bin/env bash
# Keep one open issue per LABEL in sync with a list of problems.
#   health-issue.sh LABEL TITLE PROBLEMS_FILE
# PROBLEMS_FILE holds one problem per line; empty means healthy.
# - problems, no open issue      -> open one
# - problems changed             -> update the issue body and comment
# - same problems as last time   -> nothing (no daily noise)
# - healthy and an open issue    -> comment and close it
# Needs GH_TOKEN (issues: write), GH_REPO and RUN_URL in the environment.
set -euo pipefail

label="$1"
title="$2"
problems="$3"

gh label create "$label" --color d93f0b --description "Opened and closed by the workflows" --force >/dev/null

issue="$(gh issue list --label "$label" --state open --json number --jq '.[0].number // empty')"

if [ -s "$problems" ]; then
  body="$(
    echo "Problems found by the latest run ($RUN_URL):"
    echo
    sed 's/^/- /' "$problems"
    echo
    echo "What to do for each one: https://github.com/$GH_REPO/blob/main/docs/maintenance.md."
    echo "This issue is updated when the problems change and closed when a run is healthy."
  )"
  if [ -z "$issue" ]; then
    gh issue create --title "$title" --label "$label" --body "$body"
  else
    current="$(gh issue view "$issue" --json body --jq .body | tr -d '\r')"
    # Compare only the problem lines: the run URL changes every day.
    if [ "$(grep '^- ' <<<"$current" || true)" != "$(sed 's/^/- /' "$problems")" ]; then
      gh issue edit "$issue" --body "$body"
      gh issue comment "$issue" --body "The problems changed in $RUN_URL; the description is updated."
    fi
  fi
elif [ -n "$issue" ]; then
  gh issue close "$issue" --comment "Healthy again in $RUN_URL."
fi
