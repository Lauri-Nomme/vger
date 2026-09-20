#!/usr/bin/env python3
"""Read-only NNTP client for public-inbox archives (lore.kernel.org).

lore exposes the kernel mailing lists over NNTP on nntp.lore.kernel.org, in
newsgroups named org.kernel.vger.<list> (e.g. netdev -> org.kernel.vger.netdev,
linux-kernel -> org.kernel.vger.linux-kernel).

This is deliberately tiny and stdlib-only: no Anubis/JS required, plaintext
NNTP on port 119, Message-Id based retrieval.

Usage:
    nntp.py groups [--pattern <regex>]
    nntp.py fetch   <group> <message-id> [-o file.eml]
    nntp.py article <group> <article-number> [-o file.eml]
"""
import argparse
import re
import socket
import sys

DEFAULT_HOST = "nntp.lore.kernel.org"
DEFAULT_PORT = 119


class Nntp:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=30):
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
        return r

    def stat(self, message_id):
        return self._cmd("STAT <%s>" % message_id)

    def article(self, number):
        r = self._cmd("ARTICLE %s" % number)
        if not r.startswith("220"):
            raise RuntimeError("ARTICLE: %s" % r)
        lines = []
        while True:
            line = self._f.readline()
            if not line or line == b".\r\n":
                break
            if line.startswith(b".."):
                line = line[1:]
            lines.append(line.decode(errors="replace"))
        return "".join(lines)

    def article_by_id(self, message_id):
        r = self.stat(message_id)
        if not r.startswith("223"):
            return None
        return self.article(r.split()[1])

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


def _save_or_print(body, output, label):
    if output:
        with open(output, "w") as fh:
            fh.write(body)
        print("saved %s (%d bytes)" % (output, len(body)))
    else:
        sys.stdout.write(body)


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
            _save_or_print(body, a.output, "fetch")
        elif a.cmd == "article":
            n.group(a.group)
            _save_or_print(n.article(str(a.number)), a.output, "article")
    finally:
        n.close()


if __name__ == "__main__":
    main()