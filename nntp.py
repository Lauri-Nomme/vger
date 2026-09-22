#!/usr/bin/env python3
"""Read-only NNTP client for public-inbox archives (lore.kernel.org).

lore exposes the kernel mailing lists over NNTP on nntp.lore.kernel.org, in
newsgroups named org.kernel.vger.<list> (e.g. netdev -> org.kernel.vger.netdev,
linux-kernel -> org.kernel.vger.linux-kernel).

Stdlib-only, plaintext NNTP on port 119, Message-Id based retrieval. Also
resolves a whole thread (ancestors from References, descendants by scanning the
overview) so you can see who replied to a patch without a browser.

Usage:
    nntp.py groups  [--pattern <regex>]
    nntp.py fetch   <group> <message-id> [-o file.eml]
    nntp.py article <group> <article-number> [-o file.eml]
    nntp.py thread  [--group <group>] <message-id> [--max-scan N]
"""
import argparse
import re
import socket
import sys

DEFAULT_HOST = "nntp.lore.kernel.org"
DEFAULT_PORT = 119
DEFAULT_GROUP = "org.kernel.vger.netdev"


def _bare(mid):
    return (mid or "").strip().strip("<>")


class Nntp:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=60):
        self._sock = socket.create_connection((host, port), timeout)
        self._f = self._sock.makefile("rwb")
        self.greeting = self._readline()

    def _readline(self):
        line = self._f.readline()
        return line.decode(errors="replace").rstrip("\r\n") if line else ""

    def _cmd(self, text):
        self._f.write((text + "\r\n").encode())
        self._f.flush()
        return self._readline()

    def group(self, name):
        r = self._cmd("GROUP %s" % name)
        if not r.startswith("211"):
            raise RuntimeError("GROUP %s: %s" % (name, r))
        _count, _first, last, _name = r.split()[1:5]
        self.last = int(last)
        return r

    def stat(self, message_id):
        return self._cmd("STAT <%s>" % _bare(message_id))

    def number(self, message_id):
        r = self.stat(message_id)
        return int(r.split()[1]) if r.startswith("223") else None

    def _read_article(self):
        lines = []
        while True:
            line = self._f.readline()
            if not line or line == b".\r\n":
                break
            if line.startswith(b".."):
                line = line[1:]
            lines.append(line.decode(errors="replace"))
        return "".join(lines)

    def article(self, number):
        r = self._cmd("ARTICLE %s" % number)
        if not r.startswith("220"):
            raise RuntimeError("ARTICLE: %s" % r)
        return self._read_article()

    def article_by_id(self, message_id):
        n = self.number(message_id)
        return self.article(n) if n else None

    def headers(self, number):
        body = self.article(number)
        head = body.split("\n\n", 1)[0]
        hdr = {}
        for line in head.splitlines():
            if line[:1] in (" ", "\t"):
                continue
            k, _, v = line.partition(":")
            hdr[k.lower().strip()] = v.strip()
        return hdr

    def xover(self, start, end):
        for cmd in ("XOVER", "OVER"):
            r = self._cmd("%s %d-%d" % (cmd, start, end))
            if r.startswith("224"):
                rows = []
                while True:
                    line = self._f.readline()
                    if not line or line == b".\r\n":
                        break
                    parts = line.decode(errors="replace").rstrip("\r\n").split("\t")
                    if len(parts) < 6:
                        continue
                    rows.append({
                        "num": int(parts[0]),
                        "subject": parts[1],
                        "from": parts[2],
                        "date": parts[3],
                        "mid": _bare(parts[4]),
                        "refs": [_bare(x) for x in parts[5].split()],
                    })
                return rows
        return []

    def list_groups(self, pattern=None):
        self._cmd("LIST")
        out = []
        while True:
            line = self._f.readline()
            if not line or line == b".\r\n":
                break
            grp = line.decode(errors="replace").split()[0]
            if not pattern or re.search(pattern, grp):
                out.append(grp)
        return out

    def close(self):
        try:
            self._cmd("QUIT")
        except Exception:
            pass
        try:
            self._sock.close()
        except Exception:
            pass


def _save_or_print(body, output):
    if output:
        with open(output, "w") as fh:
            fh.write(body)
        print("saved %s (%d bytes)" % (output, len(body)))
    else:
        sys.stdout.write(body)


def cmd_thread(n, group, msgid, max_scan):
    n.group(group)
    seed = _bare(msgid)
    seed_num = n.number(seed)
    if seed_num is None:
        print("Message-Id not found in %s: <%s>" % (group, seed), file=sys.stderr)
        return 1

    hdr = n.headers(seed_num)
    ids = {seed}
    for field in ("references", "in-reply-to"):
        for x in (hdr.get(field) or "").split():
            ids.add(_bare(x))
    nums = [seed_num]
    for i in list(ids):
        num = n.number(i)
        if num:
            nums.append(num)
    root = min(nums)
    end = n.last
    truncated = False
    if end - root > max_scan:
        end = root + max_scan
        truncated = True

    rows = n.xover(root, end)
    known = set(ids)
    changed = True
    while changed:
        changed = False
        for r in rows:
            if r["mid"] in known:
                continue
            if any(x in known for x in r["refs"]):
                known.add(r["mid"])
                changed = True

    thread = sorted((r for r in rows if r["mid"] in known), key=lambda r: r["num"])
    replies = [r for r in thread if seed in r["refs"]]
    print("thread of <%s>  (%s)" % (seed, group))
    print("  %d message(s), %d direct repl%s%s"
          % (len(thread), len(replies), "y" if len(replies) == 1 else "ies",
             "  [scan truncated]" if truncated else ""))
    print()
    for r in thread:
        mark = "*" if r["mid"] == seed else ("+" if seed in r["refs"] else " ")
        print("%s #%-8d %s  %-38s %s"
              % (mark, r["num"], r["date"][:31], r["from"][:38], r["subject"][:72]))
    print("\n(* = the message you asked about, + = direct reply to it)")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Read-only NNTP client for lore archives")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_groups = sub.add_parser("groups", help="list newsgroups")
    p_groups.add_argument("--pattern")

    p_fetch = sub.add_parser("fetch", help="fetch a message by Message-Id")
    p_fetch.add_argument("group")
    p_fetch.add_argument("message_id")
    p_fetch.add_argument("-o", "--output")

    p_art = sub.add_parser("article", help="fetch an article by number")
    p_art.add_argument("group")
    p_art.add_argument("number", type=int)
    p_art.add_argument("-o", "--output")

    p_thread = sub.add_parser("thread", help="show a whole thread and its replies")
    p_thread.add_argument("message_id")
    p_thread.add_argument("--group", default=DEFAULT_GROUP)
    p_thread.add_argument("--max-scan", type=int, default=60000,
                          help="max overview articles to scan forward (default 60000)")

    a = ap.parse_args()
    n = Nntp(a.host, a.port)
    try:
        if a.cmd == "groups":
            for grp in n.list_groups(a.pattern):
                print(grp)
        elif a.cmd == "fetch":
            n.group(a.group)
            body = n.article_by_id(a.message_id)
            if body is None:
                print("Message-Id not found in %s" % a.group, file=sys.stderr)
                sys.exit(1)
            _save_or_print(body, a.output)
        elif a.cmd == "article":
            n.group(a.group)
            _save_or_print(n.article(str(a.number)), a.output)
        elif a.cmd == "thread":
            sys.exit(cmd_thread(n, a.group, a.message_id, a.max_scan))
    finally:
        n.close()


if __name__ == "__main__":
    main()
