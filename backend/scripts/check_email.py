"""Check that the platform can send e-mail, and say plainly why if it cannot.

    cd backend
    python scripts/check_email.py                      # connect and sign in
    python scripts/check_email.py you@example.com      # and send one message

This exists because the alternative is asking somebody to paste a password
into a file, restart a server, invite a colleague, and wait to see whether an
e-mail arrives — with nothing to look at in between if it does not. This takes
about two seconds and ends with a yes or a no.

It prints no password, so the output is safe to copy into a message when
asking for help.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.services import mail  # noqa: E402

GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[1;33m"
BOLD = "\033[1m"
OFF = "\033[0m"


def main(argv: list[str]) -> int:
    recipient = argv[1] if len(argv) > 1 else None

    print()
    print(f"{BOLD}Checking the e-mail settings{OFF}")
    print()
    print(f"  Server    {settings.SMTP_HOST or '(not set)'}:{settings.SMTP_PORT}")
    print(f"  Account   {settings.SMTP_USERNAME or '(not set)'}")
    # Length only. A password in a terminal is a password in a screenshot.
    secret = settings.SMTP_PASSWORD or ""
    print(f"  Password  {'set, ' + str(len(secret)) + ' characters' if secret else '(not set)'}")
    print(f"  Sends as  {settings.mail_sender or '(nothing to send as)'}")
    print(
        f"  Security  {'SSL' if settings.SMTP_SSL else 'STARTTLS' if settings.SMTP_STARTTLS else 'none'}"
    )
    print()

    # A Gmail App Password pasted in Google's four-groups-of-four display form
    # is un-grouped when the settings load, so by this point it is already
    # right. Anything else with a space in it is kept exactly as typed — which
    # is correct, and worth saying, because a space is the first thing anybody
    # suspects when a password is refused.
    if secret and " " in secret:
        print(f"{YELLOW}  The password contains spaces, and was used as typed.{OFF}")
        print("  That is right for a provider whose passwords have spaces in them.")
        print("  A Gmail App Password does not: it is 16 letters, and the spaces")
        print("  Google shows are only for reading. Those are removed for you.")
        print()

    print("Connecting...")
    result = mail.check()

    if not result.ok:
        print()
        print(f"{RED}Not working.{OFF}")
        print()
        for line in result.detail.splitlines():
            print(f"  {line}")
        print()
        return 1

    print()
    print(f"{GREEN}Working.{OFF}")
    for line in result.detail.splitlines():
        print(f"  {line}")
    print()

    if not recipient:
        print("To send a real message as well, run it again with an address:")
        print("    python scripts/check_email.py you@example.com")
        print()
        return 0

    print(f"Sending a test message to {recipient}...")
    sent = mail.send(
        recipient,
        "Stratum: e-mail is working",
        "If you are reading this, the platform can send e-mail.\n\n"
        "Nothing else needs doing. This message was sent by\n"
        "scripts/check_email.py and means the settings are right.\n",
    )

    if not sent.ok:
        print()
        print(f"{RED}It signed in but could not send.{OFF}")
        print()
        for line in sent.detail.splitlines():
            print(f"  {line}")
        print()
        return 1

    print()
    print(f"{GREEN}Sent.{OFF} Check {recipient} — including the spam folder the first time.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
