#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Writes the release notes of a tag to stdout: the subjects of the commits since the previous tag (one
# bullet each, merges left out) and a link to the full comparison. Used by the release workflow and,
# for a preview, by .github/pre-release.sh.
#
#   .github/release-notes.sh <tag or commit> [<previous tag>]    (default: the tag before it)
set -euo pipefail
to="${1:?usage: release-notes.sh <tag or commit> [<previous tag>]}"
from="${2:-$(git describe --tags --abbrev=0 "$to^" 2>/dev/null || true)}"
repo="${GITHUB_REPOSITORY:-transfairs/A2G-Linux}"
range="${from:+$from..}$to"
changes="$(git log --no-merges --reverse --format='- %s' "$range")"
if [[ -z "$changes" ]]; then
  echo "release-notes.sh: no commits in $range" >&2
  exit 1
fi
echo "## Changes"
echo
echo "$changes"
if [[ -n "$from" ]]; then
  echo
  echo "**Full Changelog**: https://github.com/$repo/compare/$from...$to"
fi
