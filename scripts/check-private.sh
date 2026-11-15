#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Rev. J. Money
#
# Keep private details out of the repo. Checks every tracked and staged file (plus any given) against:
#   local/private-patterns.txt  one extended regex per line (LAN addresses, MACs, host and user names ...)
#   local/private-secrets.txt   one secret source per line: PATH, or PATH<TAB>PREFIX (the value after PREFIX on
#                               the first line starting with it); the default is the file's first line
# Both live in local/, which git ignores, so the patterns themselves never get committed. Secrets are compared,
# never printed. Exit 1 names each file with a hit; exit 3 when there is nothing personal to check against.
# usage: scripts/check-private.sh [extra files...]
cd "$(git rev-parse --show-toplevel)" || exit 2
patterns=()
if [ -f local/private-patterns.txt ]; then
    while IFS= read -r line; do
        line="${line%$'\r'}"
        [ -n "$line" ] && [ "${line:0:1}" != "#" ] && patterns+=("$line")
    done < local/private-patterns.txt
fi
secrets=()
if [ -f local/private-secrets.txt ]; then
    while IFS=$'\t' read -r path prefix; do
        path="${path%$'\r'}"; prefix="${prefix%$'\r'}"
        [ -n "$path" ] && [ "${path:0:1}" != "#" ] && [ -s "$path" ] || continue
        if [ -n "$prefix" ]; then
            v="$(grep -i -m1 "^$prefix" "$path" | cut -c$((${#prefix} + 1))- | tr -d ' \r\n')"
        else
            v="$(head -1 "$path" | tr -d '\r\n')"
        fi
        [ -n "$v" ] && secrets+=("$v")
    done < local/private-secrets.txt
fi
if [ ${#patterns[@]} -eq 0 ] && [ ${#secrets[@]} -eq 0 ]; then
    echo "privacy check: nothing personal to check against (add local/private-patterns.txt, local/private-secrets.txt)"
    exit 3
fi
mapfile -t files < <( { git ls-files; git diff --cached --name-only; printf '%s\n' "$@"; } | sort -u)
bad=0
for f in "${files[@]}"; do
    [ -f "$f" ] || continue
    for p in "${patterns[@]}"; do
        if grep -qiE "$p" "$f"; then echo "PRIVATE: $f matches a pattern (line $(grep -niE "$p" "$f" | head -1 | cut -d: -f1))"; bad=1; fi
    done
    for s in "${secrets[@]}"; do
        grep -qF "$s" "$f" && { echo "PRIVATE: $f contains a secret (not shown)"; bad=1; }
    done
done
[ $bad -eq 0 ] && echo "privacy check: clean (${#files[@]} files, ${#patterns[@]} patterns, ${#secrets[@]} secrets)"
exit $bad
