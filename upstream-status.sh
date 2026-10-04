#!/usr/bin/env bash
# upstream-status.sh - where did a merged commit get to?
#
# Reports:
#   * mainline (torvalds/linux): present? current tree version / latest -rc tag
#   * net-next: present?
#   * stable (released) + stable-rc (staging): has the backport landed?
#   * stable mailing list: is the backport mail out yet?
#   * optionally post a summary to an ntfy topic (only when the state changed)
#
# Usage:
#   upstream-status.sh <sha> [--file <path>] [--subject "subsystem: short commit subject"]
#       [--branches "6.18.y 6.12.y 6.6.y 6.1.y 5.15.y"]
#       [--stable-group org.kernel.vger.stable] [--list-scan 8000]
#       [--ntfy http://ntfy.host/<topic>] [--state /path/state]
#
# Detection:
#   * mainline / net-next keep the merged SHA -> /commit/?id=<sha> HTTP 200.
#   * stable backports get a NEW sha -> grep the branch's log of <file> for the
#     subject (cgit ?qt=grep is disabled on git.kernel.org, so use the file log).
#   * the stable list is scanned over NNTP (org.kernel.vger.stable) for the
#     backport subject, so you hear about the mail before it lands in a tree.
set -u

SHA=""; SUBJECT=""; FILE=""
BRANCHES="6.18.y 6.12.y 6.6.y 6.1.y 5.15.y"
STABLE_GROUP="org.kernel.vger.stable"; LIST_SCAN=8000
NTFY="${NTFY_URL:-}"; STATE=""

while [ $# -gt 0 ]; do
	case "$1" in
		--subject)      SUBJECT="$2"; shift 2 ;;
		--file)         FILE="$2"; shift 2 ;;
		--branches)     BRANCHES="$2"; shift 2 ;;
		--stable-group) STABLE_GROUP="$2"; shift 2 ;;
		--list-scan)    LIST_SCAN="$2"; shift 2 ;;
		--ntfy)         NTFY="$2"; shift 2 ;;
		--state)        STATE="$2"; shift 2 ;;
		-h|--help)      sed -n '2,24p' "$0"; exit 0 ;;
		*)              SHA="$1"; shift ;;
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
branch_hits(){ if [ -z "$SUBJECT" ] || [ -z "$FILE" ]; then echo "-"; return; fi
	curl -s --max-time 40 "$1/log/$FILE?h=linux-$2" | grep -c -- "$SUBJECT"; }
stable_list(){ python3 - "$STABLE_GROUP" "$SUBJECT" "$LIST_SCAN" <<'PY'
import socket, sys
group, subject, limit = sys.argv[1], sys.argv[2], int(sys.argv[3])
if not subject:
	print("-"); raise SystemExit
try:
	s = socket.create_connection(("nntp.lore.kernel.org", 119), timeout=60); f = s.makefile("rwb")
	def cmd(t):
		f.write((t + "\r\n").encode()); f.flush(); return f.readline().decode(errors="replace").strip()
	f.readline(); r = cmd("GROUP " + group); p = r.split()
	if len(p) < 4:
		print("n/a"); raise SystemExit
	lo, hi = int(p[2]), int(p[3]); rows = []
	resp = cmd("XHDR subject %d-%d" % (max(lo, hi - limit), hi))
	if resp.startswith("221"):
		while True:
			l = f.readline()
			if not l or l == b".\r\n": break
			rows.append(l.decode(errors="replace").rstrip("\r\n"))
	else:
		resp = cmd("XOVER %d-%d" % (max(lo, hi - limit), hi))
		if resp.startswith("224"):
			while True:
				l = f.readline()
				if not l or l == b".\r\n": break
				c = l.decode(errors="replace").rstrip("\r\n").split("\t")
				if len(c) > 1: rows.append(c[0] + " " + c[1])
	s.close()
	hits = [x for x in rows if subject.lower() in x.lower()]
	print("hits: %d (scanned %d subjects)" % (len(hits), len(rows)))
	for h in hits[-5:]:
		print("    " + h[:110])
except Exception as e:
	print("n/a (%s)" % e)
PY
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
	out+="stable mailing list ($STABLE_GROUP):"$'\n'
	out+="$(stable_list)"$'\n'
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
