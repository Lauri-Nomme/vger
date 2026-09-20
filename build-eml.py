#!/usr/bin/env python3
"""build-eml.py - turn `git format-patch` output into a ready-to-send RFC822 email.

Parses the format-patch header block for the From:/Date:/Subject: defaults,
keeps the rest of the file (commit body + diff) as the message body verbatim,
and wraps everything in fresh RFC822 headers that you supply. Pipe the result
into send.py:

    git format-patch -1 --stdout --subject-prefix="PATCH net v2" > /tmp/v2.patch
    python3 build-eml.py --to netdev@vger.kernel.org \
            --from 'Name <addr@example.com>' \
            --cc 'Reviewer <r@example.com>' \
            --in-reply-to '<v1-message-id@example.com>' \
            --notes-file /tmp/notes.txt \
            /tmp/v2.patch > /tmp/v2.eml
    python3 send.py --relay smtp.example.com:25 --from-addr '...' \
            --to netdev@vger.kernel.org --dry-run /tmp/v2.eml

--notes-file content lands in the email-only zone (right after the commit
body's `---` separator and before the diffstat), so `git am` strips it from
the applied commit - the standard place for "Version 2:" changelogs.
"""
import argparse
import datetime
import re
import secrets


def parse_header_block(lines):
    hdr = {}
    for ln in lines:
        m = re.match(r"^([A-Za-z-]+):\s*(.*)$", ln)
        if m:
            hdr.setdefault(m.group(1).lower(), m.group(2))
    return hdr


def main():
    ap = argparse.ArgumentParser(description="Wrap git format-patch output into an RFC822 email")
    ap.add_argument("--from", dest="frm",
                    help="From: header (default: parsed author shown in the patch)")
    ap.add_argument("--to", action="append", dest="tos", required=True,
                    help="To: header (repeatable)")
    ap.add_argument("--cc", action="append", dest="ccs", default=[],
                    help="Cc: header (repeatable)")
    ap.add_argument("--subject", help="Subject: (default: parsed)")
    ap.add_argument("--date", help="Date: (default: parsed, else now)")
    ap.add_argument("--message-id", help="Message-Id: (default: generated <patch-<hex>@<domain>>)")
    ap.add_argument("--in-reply-to", dest="in_reply_to",
                    help="In-Reply-To: parent Message-Id (continue a thread)")
    ap.add_argument("--references",
                    help="References: space-separated <...> (default: the in-reply-to id)")
    ap.add_argument("--notes-file",
                    help="file whose contents are placed in the email-only zone (after `---`)")
    ap.add_argument("patch", help="path to the format-patch output")
    a = ap.parse_args()

    raw = open(a.patch, "rb").read().decode("utf-8", errors="replace")
    lines = raw.splitlines()
    hdrlines, body_start = [], 0
    for i, ln in enumerate(lines):
        if not ln.strip():
            body_start = i + 1
            break
        hdrlines.append(ln)
    hdr = parse_header_block(hdrlines)

    frm = a.frm or hdr.get("from", "")
    subj = a.subject or hdr.get("subject", "")
    date = (a.date or hdr.get("date")
            or datetime.datetime.now().astimezone().strftime("%a, %d %b %Y %H:%M:%S %z"))

    domain = ""
    m = re.search(r"@([^>\s]+)", frm)
    if m:
        domain = m.group(1)
    if a.message_id:
        mid = a.message_id
        if not mid.startswith("<"):
            mid = "<" + mid + ">"
    else:
        mid = "<patch-%s@%s>" % (secrets.token_hex(16), domain or "localhost")

    body = "\n".join(lines[body_start:]) + "\n"

    if a.notes_file:
        notes = open(a.notes_file).read().rstrip("\n")
        idx = body.find("\n---\n")
        if idx != -1:
            body = body[: idx + len("\n---\n")] + "\n" + notes + "\n" + body[idx + len("\n---\n"):]

    refs = a.references
    if not refs and a.in_reply_to:
        refs = a.in_reply_to

    out = ["From: %s" % frm,
           "To: %s" % ", ".join(a.tos)]
    if a.ccs:
        out.append("Cc: %s" % ", ".join(a.ccs))
    out += ["Subject: %s" % subj,
            "Date: %s" % date,
            "Message-Id: %s" % mid]
    if a.in_reply_to:
        irl = a.in_reply_to
        irl = irl if irl.startswith("<") else "<" + irl + ">"
        out.append("In-Reply-To: %s" % irl)
    if refs:
        out.append("References: %s" % refs)
    out += ["MIME-Version: 1.0",
            "Content-Type: text/plain; charset=utf-8",
            "Content-Transfer-Encoding: 8bit",
            "",
            body.rstrip("\n")]
    sys.stdout.write("\n".join(out) + "\n")


if __name__ == "__main__":
    import sys
    main()