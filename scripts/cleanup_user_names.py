"""
One-time cleanup for users whose `name` column accidentally contains the
full display name (including the surname) — leftover from the Google
auth bug fixed in commit 5f9acee.

Usage:
    python scripts/cleanup_user_names.py            # dry-run (default)
    python scripts/cleanup_user_names.py --apply    # actually write
"""
import argparse
import re

from app.database import SessionLocal
from app.models import User


def cleaned_name(name: str, surname: str) -> str:
    """Remove `surname` from `name`, collapse whitespace. Returns name unchanged
    when there's nothing safe to strip."""
    if not name or not surname:
        return name
    if name.strip() == surname.strip():
        return name
    if surname not in name:
        return name
    new = name.replace(surname, "")
    new = re.sub(r"\s+", " ", new).strip()
    return new or name


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Write changes (default is dry-run)")
    args = parser.parse_args()

    with SessionLocal() as db:
        rows = db.query(User).filter(User.deleted == False).all()
        changes = []
        for u in rows:
            new_name = cleaned_name(u.name or "", u.surname or "")
            if new_name != (u.name or ""):
                changes.append((u, new_name))

        print(f"Total active users: {len(rows)}")
        print(f"Rows that would change: {len(changes)}\n")
        if changes:
            print(f"{'ID':>5}  {'CURRENT NAME':<35} {'SURNAME':<20} -> {'NEW NAME':<25} EMAIL")
            print("-" * 120)
            for u, new in changes:
                print(f"{u.id:>5}  {(u.name or ''):<35} {(u.surname or ''):<20} -> {new:<25} {u.email or ''}")

        if args.apply and changes:
            for u, new in changes:
                u.name = new
            db.commit()
            print(f"\nApplied: {len(changes)} rows updated.")
        elif changes:
            print("\nDry-run only. Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
