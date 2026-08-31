#!/usr/bin/env python3
"""One-off script to grant (or revoke) the whole-app platform-admin flag for
a user, directly against `DATABASE_URL`.

There's deliberately no self-serve API to become a platform admin — this
must be run manually by someone with access to the backend's `.env` /
database credentials.

Usage (run from Backend/, with the venv active so `core`/`models` import):
    python scripts/grant_platform_admin.py <email>
    python scripts/grant_platform_admin.py <email> --revoke
"""
import argparse
import sys
from pathlib import Path

# Make `core`, `models`, etc. importable when run as `python scripts/...`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from core.database import SessionLocal  # noqa: E402
from models.user import User  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("email", help="Email of the user to grant/revoke platform-admin access for")
    parser.add_argument(
        "--revoke", action="store_true", help="Revoke platform-admin access instead of granting it"
    )
    args = parser.parse_args()

    email = args.email.strip().lower()
    grant = not args.revoke

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"No user found with email {email!r} — they must sign up (OTP or Google) before this can run.")
            return 1

        if user.is_platform_admin == grant:
            verb = "already is" if grant else "is already not"
            print(f"{user.email} {verb} a platform admin — nothing to do.")
            return 0

        user.is_platform_admin = grant
        db.commit()
        db.refresh(user)

        verb = "granted" if grant else "revoked"
        print(f"{verb.capitalize()} platform-admin access for {user.email} (id={user.id}). "
              f"is_platform_admin is now {user.is_platform_admin}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
