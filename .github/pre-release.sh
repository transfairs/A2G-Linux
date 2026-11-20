#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Checks before a release tag, locally. Changes nothing in the repository and runs no git command that
# writes (only "git fetch"). Prints one line per check and a summary; exit code 1 if a check failed.
#
#   .github/pre-release.sh [--quick]    (--quick: without tox, the real game files and Docker)
#
# 1. git: on main, up to date with origin/main, what is uncommitted or untracked
# 2. tox (tests, lint, bandit, coverage, build)
# 3. the patches on the real game files (tests/test_real_exes.py); the files come from A2G_CD_EXE,
#    A2G_GOG_SETUP, A2G_2007_DVD, A2G_INNOEXTRACT, A2G_PATCHER or else from where Lutris and install.sh
#    put them: ~/Games/anstoss-2-gold (backup of anstoss2.exe), ~/Downloads (GOG installer), a mounted
#    DVD under /run/media/$USER, Lutris' innoextract, ../A2G-Patcher
# 4. gsfix.so as the release builds it (Docker), at most glibc 2.34
# 5. the release archive from the working tree: every file the lutris.net scripts use is in it
# 6. the lutris.net scripts of the last tag (those submitted) still work with this archive
# 7. the release notes the release workflow will write, and commit subjects that read badly there
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
quick=false
[[ "${1:-}" == "--quick" ]] && quick=true

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
results=()
failed=0
report() {  # report PASS|WARN|FAIL|SKIP <check> [details]
  results+=("$(printf '%-4s  %-34s %s' "$1" "$2" "${3:-}")")
  [[ "$1" == FAIL ]] && failed=1
  echo "== $1 $2${3:+: $3}"
}
tox_cmd() { if [[ -x .venv/bin/tox ]]; then .venv/bin/tox "$@"; else tox "$@"; fi; }
last_tag="$(git describe --tags --abbrev=0 2>/dev/null || true)"

# --- 1. git ----------------------------------------------------------------------------------
branch="$(git rev-parse --abbrev-ref HEAD)"
git fetch -q origin 2>/dev/null || report WARN "git fetch" "origin not reachable"
if [[ "$branch" != main ]]; then
  report FAIL "git branch" "on $branch, releases are tagged on main"
else
  behind="$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)"
  ahead="$(git rev-list --count origin/main..HEAD 2>/dev/null || echo 0)"
  if [[ "$behind" != 0 ]]; then
    report FAIL "git main" "$behind commits behind origin/main"
  else
    report PASS "git main" "$ahead commits to push"
  fi
fi
dirty="$(git status --porcelain | wc -l)"
untracked="$(git ls-files --others --exclude-standard | tr '\n' ' ')"
if [[ "$dirty" != 0 ]]; then
  report WARN "git working tree" "$dirty changed or untracked files${untracked:+ (untracked: $untracked)}"
else
  report PASS "git working tree" "clean"
fi

# --- 2. tox -----------------------------------------------------------------------------------
if $quick; then
  report SKIP "tox" "--quick"
elif tox_cmd > "$tmp/tox.log" 2>&1; then
  skipped="$(grep -o '^  py3[0-9]*: SKIP' "$tmp/tox.log" | awk '{print $1}' | tr -d ':' | tr '\n' ' ')"
  coverage="$(grep '^TOTAL' "$tmp/tox.log" | tail -1 | awk '{print $NF}')"
  report PASS "tox" "coverage $coverage${skipped:+, not installed: $skipped}"
else
  report FAIL "tox" "see the log below"
  tail -40 "$tmp/tox.log"
fi

# --- 3. real game files -----------------------------------------------------------------------
first() { for f in "$@"; do [[ -e "$f" ]] && { echo "$f"; return; }; done; }
cd_dir="$HOME/Games/anstoss-2-gold/drive_c/Spiele/Anstoss 2 Gold"
export A2G_CD_EXE="${A2G_CD_EXE:-$(first "$cd_dir/anstoss2.exe.vor-a2g-patch")}"
export A2G_GOG_SETUP="${A2G_GOG_SETUP:-$(first "$HOME"/Downloads/setup_anstoss_2_gold_*.exe)}"
export A2G_2007_DVD="${A2G_2007_DVD:-$(first /run/media/"$USER"/*/ANSTOSS_2_GOLD/.. /run/media/"$USER"/*/anstoss_2_gold/..)}"
export A2G_INNOEXTRACT="${A2G_INNOEXTRACT:-$(command -v innoextract || first "$HOME"/.local/share/lutris/runtime/innoextract*/innoextract)}"
if [[ -z "${A2G_PATCHER:-}" && -d ../A2G-Patcher/.git ]]; then
  git -C ../A2G-Patcher fetch -q origin 2>/dev/null
  if [[ "$(git -C ../A2G-Patcher rev-list --count HEAD..origin/main 2>/dev/null || echo 0)" != 0 ]]; then
    git -C ../A2G-Patcher archive origin/main | tar -x -C "$tmp" --one-top-level=a2g-patch
    export A2G_PATCHER="$tmp/a2g-patch"
    report WARN "A2G-Patcher checkout" "behind origin/main, compared with origin/main"
  else
    export A2G_PATCHER="../A2G-Patcher"
  fi
fi
if $quick; then
  report SKIP "real game files" "--quick"
else
  for v in A2G_CD_EXE A2G_GOG_SETUP A2G_2007_DVD A2G_PATCHER; do
    [[ -n "${!v:-}" ]] || report WARN "real game files" "$v not found, that part is skipped"
  done
  if tox_cmd -e py314 -- tests/test_real_exes.py -rs > "$tmp/real.log" 2>&1; then
    report PASS "real game files" "$(grep -E '[0-9]+ (passed|skipped)' "$tmp/real.log" | tail -1 | tr -d '=')"
  else
    report FAIL "real game files" "see the log below"
    tail -40 "$tmp/real.log"
  fi
fi

# --- 4. gsfix.so ------------------------------------------------------------------------------
if $quick; then
  report SKIP "gsfix.so (Docker)" "--quick"
elif ! command -v docker > /dev/null; then
  report SKIP "gsfix.so (Docker)" "docker not installed"
elif .github/build-gsfix.sh "$tmp/gsfix.so" > "$tmp/gsfix.log" 2>&1; then
  glibc="$(objdump -T "$tmp/gsfix.so" | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1)"
  if [[ "$(printf '%s\n' "$glibc" GLIBC_2.34 | sort -V | tail -1)" == GLIBC_2.34 ]]; then
    report PASS "gsfix.so (Docker)" "needs $glibc"
  else
    report FAIL "gsfix.so (Docker)" "needs $glibc, more than 2.34"
  fi
else
  report FAIL "gsfix.so (Docker)" "build failed"
  tail -20 "$tmp/gsfix.log"
fi

# --- 5. release archive from the working tree -------------------------------------------------
out="$tmp/out/A2G-Linux"
mkdir -p "$out"
git ls-files -z --cached --others --exclude-standard | while IFS= read -r -d '' f; do
  [[ -e "$f" ]] && cp --parents "$f" "$out/"
done
[[ -f "$tmp/gsfix.so" ]] && cp "$tmp/gsfix.so" "$out/src/gsfix.so"
needed() {  # the paths a lutris.net script uses inside the archive ($CACHE/a2g/...), build/ is made there
  # shellcheck disable=SC2016  # $CACHE is the literal text in the scripts
  grep -o '\$CACHE/a2g/[A-Za-z0-9_./-]*' "$@" | sed 's|.*\$CACHE/a2g/||' | grep -v '^build' | sort -u
}
missing=""
for f in $(needed lutris.net/*.yml); do
  [[ -e "$out/$f" || "$f" == src/gsfix.so ]] || missing+=" $f"
done
for f in src/a2start.exe src/a2setup.exe src/a2v101.json src/a2manager.json; do [[ -e "$out/$f" ]] || missing+=" $f"; done
if [[ -n "$missing" ]]; then
  report FAIL "release archive" "missing:$missing"
else
  report PASS "release archive" "$(find "$out" -type f | wc -l) files"
fi

# --- 6. lutris.net scripts of the last tag ----------------------------------------------------
if [[ -z "$last_tag" ]]; then
  report SKIP "lutris.net scripts of last tag" "no tag yet"
else
  options="$(python3 src/a2patch.py --help)"
  problems=""
  for f in $(git ls-tree --name-only "$last_tag" lutris.net/ | grep '\.yml$'); do
    git show "$last_tag:$f" > "$tmp/old.yml"
    for p in $(needed "$tmp/old.yml"); do
      [[ -e "$out/$p" || "$p" == src/gsfix.so ]] || problems+=" $f: $p missing;"
    done
    while read -r o; do
      grep -q -- "$o" <<< "$options" || problems+=" $f: a2patch.py $o gone;"
    done < <(grep -o 'a2patch.py" [-a-z0-9 ]*' "$tmp/old.yml" | grep -o -- '--[a-z0-9-]*' | sort -u)
    while read -r o; do
      grep -q -- "\"$o\"" install.sh || problems+=" $f: install.sh $o gone;"
    done < <(grep -o 'install.sh" --[a-z-]*' "$tmp/old.yml" | grep -o -- '--[a-z-]*' | sort -u)
  done
  if [[ -n "$problems" ]]; then
    report FAIL "lutris.net scripts of $last_tag" "${problems% ;}"
  elif git diff --quiet "$last_tag" -- lutris.net/; then
    report PASS "lutris.net scripts of $last_tag" "work with the new archive, unchanged"
  else
    report WARN "lutris.net scripts of $last_tag" "work with the new archive; changed since, submit them after the release"
  fi
fi

# --- 7. release notes -------------------------------------------------------------------------
if notes="$(.github/release-notes.sh HEAD "$last_tag" 2>/dev/null)"; then
  bad="$(git log --no-merges --format='%s' "${last_tag:+$last_tag..}HEAD" | grep -iE '^(wip|fix|tmp|test|update|changes?)$|^.{0,15}$' || true)"
  if [[ -n "$bad" ]]; then
    report WARN "release notes" "subjects that read badly: $(tr '\n' ';' <<< "$bad")"
  else
    report PASS "release notes" "$(grep -c '^- ' <<< "$notes") entries"
  fi
  printf '%s\n' "$notes" > "$tmp/notes.md"
else
  report WARN "release notes" "no commits since $last_tag, the release workflow would fail"
fi

echo
echo "Summary (last tag: ${last_tag:-none})"
printf '%s\n' "${results[@]}"
if [[ -f "$tmp/notes.md" ]]; then
  echo
  echo "Release notes preview:"
  cat "$tmp/notes.md"
fi
exit "$failed"
