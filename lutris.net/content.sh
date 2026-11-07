#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Writes the content for the "Content" field on lutris.net to lutris.net/content.yml: everything
# below "script:" of an installer script, one indentation level less.
#
#   lutris.net/content.sh [script]    (default: lutris.net/anstoss-2-gold.yml, the CD version)
set -euo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
src="${1:-$dir/anstoss-2-gold.yml}"
out="$dir/content.yml"
grep -q '^script:$' "$src" || { echo "$src: no line \"script:\"" >&2; exit 1; }
sed -n '/^script:$/,$p' "$src" | tail -n +2 | sed 's/^  //' > "$out"
echo "$out written from $src ($(wc -l < "$out") lines)"
