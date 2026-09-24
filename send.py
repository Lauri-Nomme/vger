#!/usr/bin/env python3
"""Send a raw RFC822 message (.eml / format-patch output) through an SMTP relay.

Deliberately stdlib-only. The message file is submitted verbatim, so every
header you put in it (From, Subject, In-Reply-To, References, Message-Id,
MIME) is preserved exactly. The ENVELOPE sender (MAIL FROM) and recipients
are given on the command line and do not have to match the headers - keep
them consistent with the From you want.

Usage:
    send.py --relay host[:port] --from-addr 'Name <addr@example.com>' \\
            --to list@vger.kernel.org --to ack@example.com \\
            [--cc another@example.com] [--helo mail.example.com] \\
            [--tls] [--auth user] [--dry-run] message.eml

Anonymity notes (your responsibility):
  - The From: header in the file must be the identity you intend to post
    under. There must be no Reply-To:/Sender:/X-* header pointing elsewhere.
  - The relay will append Received: headers showing its own hostname/IP and,
    often, the client hostname it reverse-maps from your source address. On a
    LAN relay that typically resolves to your internal hostname - if that
    matters to you, control it in the relay's config (/etc/hosts, myorigin)
    or use an exit that anonymizes it.
"""
import argparse
import getpass
import os
import re
import smtplib
import sys


def parse_relay(spec):
    host, _, port = spec.partition(":")
    return host, int(port or 25)


def main():
    ap = argparse.ArgumentParser(description="Submit an RFC822 message through an SMTP relay")
    ap.add_argument("--relay", required=True, help="SMTP relay host[:port]")
    ap.add_argument("--from-addr", dest="from_addr", required=True,
                    help="envelope sender (MAIL FROM)")
    ap.add_argument("--to", action="append", dest="tos", required=True,
                    help="envelope recipient (repeatable)")
    ap.add_argument("--cc", action="append", dest="ccs", default=[],
                    help="additional envelope recipient (repeatable)")
    ap.add_argument("--helo", default=None,
                    help="EHLO/HELO name (default: domain of --from-addr)")
    ap.add_argument("--tls", action="store_true",
                    help="STARTTLS before MAIL (required for port 587/public relays)")
    ap.add_argument("--auth", dest="auth_user", default=None,
                    help="SMTP AUTH username (password from env SMTP_PASS or prompt)")
    ap.add_argument("--dry-run", action="store_true",
                    help="EHLO + MAIL + RCPT, then RSET; send no DATA")
    ap.add_argument("message", help="path to the raw .eml/.patch to send")
    a = ap.parse_args()

    host, port = parse_relay(a.relay)
    helo = a.helo
    if not helo:
        m = re.search(r"@([^>\s]+)", a.from_addr)
        helo = m.group(1) if m else "localhost"

    data = open(a.message, "rb").read()
    rcpts = a.tos + a.ccs
    if not rcpts:
        print("no recipients", file=sys.stderr)
        sys.exit(2)

    s = smtplib.SMTP(host, port, timeout=40)
    try:
        s.ehlo(helo)
        if a.tls:
            code = s.starttls()[0]
            if code != 220:
                raise RuntimeError("STARTTLS refused")
            s.ehlo(helo)
        if a.auth_user:
            pw = os.environ.get("SMTP_PASS") or getpass.getpass("SMTP password: ")
            s.login(a.auth_user, pw)
        if a.dry_run:
            s.mail(a.from_addr)
            for r in rcpts:
                code = s.rcpt(r)[0]
                if code not in (250, 251, 252):
                    print("RCPT %s refused (%d)" % (r, code), file=sys.stderr)
                    sys.exit(3)
            s.rset()
            print("dry-run: relay accepted MAIL FROM and all RCPTs (no DATA sent)")
        else:
            res = s.sendmail(a.from_addr, rcpts, data)
            if res:
                print("rejected recipients: %s" % res, file=sys.stderr)
                sys.exit(4)
            print("accepted: %s (%d bytes)" % (", ".join(rcpts), len(data)))
    finally:
        try:
            s.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()