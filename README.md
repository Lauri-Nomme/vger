# vger — kernel mailing-list tooling (read + submit)

Small, stdlib-only tools for working with the kernel mailing lists over
NWTP (read) and SMTP (submit), useful when upstreaming patches (netdev,
linux-kernel, ...).

- `nntp.py` — read-only NNTP client for the **lore** public-inbox archives
  (`nntp.lore.kernel.org:119`). No browser/JS needed, works behind firewalls
  that block the Anubis-gated web UI.
- `send.py` — submits a raw RFC822 message (e.g. `git format-patch`
  output) verbatim through an SMTP relay.

Both are pure Python 3 standard library. Run anywhere with `python3`.

---

## nntp.py — read from the archives

lore newsgroups are named `org.kernel.vger.<list>` (dots, not dashes):

| list | newsgroup |
|---|---|
| netdev | `org.kernel.vger.netdev` |
| linux-kernel | `org.kernel.vger.linux-kernel` |
| linux-mediatek | `org.infradead.lists.linux-mediatek` |
| stable | `org.kernel.vger.stable` |

```
# list groups (regex filter)
python3 nntp.py groups --pattern netdev

# fetch a message by Message-Id (saves a full mbox-style RFC822 file)
python3 nntp.py fetch org.kernel.vger.netdev \
    '<your-message-id@example.com>' -o /tmp/msg.eml

# fetch by article number instead
python3 nntp.py article org.kernel.vger.netdev 1270493 -o /tmp/msg.eml
```

Finding a message-id: from any lore URL/thread you already have, the
`Message-Id` header is the authoritative key (nntp `STAT` accepts it even
before the article is indexed in a search engine).

## send.py — submit a patch/mail

Build the message exactly as it should appear on the list, then submit it:

```
# 1. produce the patch as an email (a revision goes out as a NEW thread:
#    do not add In-Reply-To/References pointing at the previous version)
git format-patch -1 --stdout --subject-prefix="PATCH v2 net" > /tmp/v2.patch
#    (edit the header block: Subject, and add your From when hand-crafting)

# 2. dry-run first (EHLO/MAIL/RCPT only, no DATA)
python3 send.py \
    --relay smtp.example.com:587 \
    --from-addr 'Some Author <author@example.com>' \
    --to netdev@vger.kernel.org \
    --cc 'Reviewer <r@example.com>' \
    --helo author.example.com --tls --auth author@example.com \
    --dry-run /tmp/v2.patch

# 3. send for real (SMTP_PASS env or prompt for AUTH password)
SMTP_PASS='...' python3 send.py \
    --relay smtp.example.com:587 --from-addr '...' --to netdev@vger.kernel.org \
    --cc '...' --helo author.example.com --tls --auth author@example.com \
    /tmp/v2.patch
```

Notes on good practice:

- **Envelope vs headers.** `--from-addr`/`--to`/`--cc` set the envelope
  (MAIL FROM / RCPT). The message file itself carries the visible
  `From:`/`To:`/`Cc:` headers. Keep them consistent.
- **Threading vs. new series versions** — two different things:
  - A *reply to a reviewer* (answering feedback, acknowledging points) is a
    reply: set `In-Reply-To:`/`References:` to the message it answers (b4 and
    `git send-email` do this automatically).
  - A *new version of a patch series* (**v2, v3, ...**) must be a **fresh,
    independent thread** — do **not** set `In-Reply-To:`/`References:` to the
    previous version. On netdev this is enforced by the `netdev-bot`
    patch-validation bot (Cc's `kuba@kernel.org`): reply-versions break the
    tooling (patchwork/b4 series tracking) and are easy for busy reviewers to
    miss. Progress is tracked solely by the `[PATCH vN <tree>]` subject
    prefix, so each revision goes out as a new top-level message with the
    version bumped. If the bot warns you after a send, do **not** repost to
    "fix" it — just apply the rule to the next revision.
- **Versioning.** Bump `[PATCH]` → `[PATCH v2]` via `--subject-prefix` (or
  hand-edit Subject), and add a `Version 2:` changelog between the commit
  body's `---` and the diff so `git am` strips it.
- **Fixes/CC stable.** For bug fixes include `Fixes: <12-hex> ("<subject>")`
  in the commit message and Cc stable@vger.kernel.org.

## Anonymity / opsec checklist (when it matters)

1. The `From:` header and the envelope `MAIL FROM` must both be the posting
   identity — never the personal one. There must be no `Reply-To:`,
   `Sender:`, or `X-*` header adding another address.
2. Proofread the message body for stray identifiers (hostnames, private
   IPs, internal paths) before sending.
3. The relay appends a `Received:` chain. On a LAN relay it usually shows
   the *relay's* hostname and the *client* address it reverse-maps from
   (often your `--helo`/internal hostname and a private IP). If that exposure
   is a concern, control it in the relay's configuration (`/etc/hosts`,
   `myorigin`/`myhostname` in Postfix) rather than in the client, and send
   over TLS when the relay is not under your control.
4. Verify what actually landed with:

```
python3 nntp.py fetch <group> '<message-id>' -o /tmp/landed.eml
# check From/Subject/In-Reply-To/References and the Received chain
```

## Requirements / limits

- Python ≥ 3.6, no third-party packages.
- lore NNTP is plaintext on port 119 (no STARTTLS there); read-only is fine.
- `send.py` talks STARTTLS on demand (e.g. 587 / public relays); for a
  local/trusted relay plaintext on 25 works.