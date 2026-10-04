#!/usr/bin/env bash
# upstream-status.sh - where did a merged commit get to?
#
# Reports:
#   * mainline (torvalds/linux): present? current tree version / latest -rc tag
#   * net-next: present?
#   * stable (released) + stable-rc (staging): has the backport landed?
#   * optionally post a summary to an ntfy topic (only when the state changed)
#
# Usage:
#   upstream-status.sh <sha> [--file <path>] [--subject "subsystem: short commit subject"]
#       [--branches "6.18.y 6.12.y 6.6.y 6.1.y 5.15.y"]
#       [--ntfy http://ntfy.host/<topic>] [--state /path/state]
#
# How detection works:
#   * mainline / net-next keep the merged SHA -> /commit/?id=<sha> HTTP 200.
#   * stable backports get a NEW sha, so they are found by grepping the branch's
#     log of <file> for the commit subject (--subject).  NOTE: cgit's
#     ?qt=grep search is disabled on git.kernel.org, so the file log is used.
set -u

SHA=""; SUBJECT=""; FILE=""
BRANCHES="6.18.y 6.12.y 6.6.y 6.1.y 5.15.y"
NTFY="${NTFY_URL:-}"; STATE=""

while [ $# -gt 0 ]; do
	case "$1" in
		--subject)  SUBJECT="$2"; shift 2 ;;
		--file)     FILE="$2"; shift 2 ;;
		--branches) BRANCHES="$2"; shift 2 ;;
		--ntfy)     NTFY="$2"; shift 2 ;;
		--state)    STATE="$2"; shift 2 ;;
		-h|--help)  sed -n '2,22p' "$0"; exit 0 ;;
		*)          SHA="$1"; shift ;;
	esac
done
[ -n "$SHA" ] || { echo "usage: $0 <sha> [--file path] [--subject ...] [--ntfy url]" >&2; exit 2; }

MAIN=https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git
NEXT=https://git.kernel.org/pub/scm/linux/kernel/git/netdev/net-next.git
STABLE=https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git
STABLERC=https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux-stable-rc.git

has_commit() { [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$1/commit/?id=$SHA")" = "200" ]; }
ver()        { curl -s --max-time 30 "$1/plain/Makefile" | awk '/^VERSION/{v=$3}/^PATCHLEVEL/{p=$3}/^SUBLEVEL/{s=$3}/^EXTRAVERSION/{e=$3}END{print v"."p"."s e}'; }
latest_rc()  { curl -s --max-time 30 "$1/refs/tags" | grep -oE 'v[0-9]+\.[0-9]+-rc[0-9]+' | sort -V | tail -1; }
branch_hits(){ # $1=repo $2=branch : count commit titles in the file log
	if [ -z "$SUBJECT" ] || [ -z "$FILE" ]; then echo "-"; return; fi
	curl -s --max-time 40 "$1/log/$FILE?h=linux-$2" | grep -c -- "$SUBJECT"
}

mp=no; has_commit "$MAIN" && mp=yes
np=no; has_commit "$NEXT" && np=yes
out="commit  $SHA"$'\n'
out+="mainline:  $mp  (tree $(ver "$MAIN"), latest tag $(latest_rc "$MAIN"))"$'\n'
out+="net-next:  $np"$'\n'
if [ -n "$SUBJECT" ]; then
	out+="backport subject: \"$SUBJECT\"  (file: ${FILE:-<unset>})"$'\n'
	out+="stable branches (released):"$'\n'
	for b in $BRANCHES; do out+="  linux-$b: $(branch_hits "$STABLE" "$b")"$'\n'; done
	out+="stable-rc (staging):"$'\n'
	for b in $BRANCHES; do out+="  linux-$b: $(branch_hits "$STABLERC" "$b")"$'\n'; done
fi
printf '%s' "$out"

if [ -n "$NTFY" ]; then
	[ -n "$STATE" ] || STATE="${XDG_CACHE_HOME:-$HOME/.cache}/vger/upstream-${SHA:0:12}.state"
	mkdir -p "$(dirname "$STATE")"
	if [ ! -f "$STATE" ] || ! cmp -s "$STATE" <(printf '%s' "$out"); then
		printf '%s' "$out" > "$STATE"
		if curl -s -o /dev/null --max-time 20 -H "Title: upstream status ${SHA:0:12}" -H "Tags: satellite" --data-binary "$out" "$NTFY"; then
			echo "(ntfy: posted change)"
		else
			echo "(ntfy: post failed)" >&2
		fi
	else
		echo "(ntfy: no change since last run)"
	fi
fi
