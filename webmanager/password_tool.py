from __future__ import annotations

"""Offline recovery tool for the Web Manager SQLite account database.

This file is intentionally kept for compatibility with earlier packages that
shipped ``python -m webmanager.password_tool``. Web Manager 1.1+ no longer uses
``auth.json``; accounts live in SQLite. The tool may create the *first*
superadmin on an empty database or reset an existing account password. It never
creates a second superadmin or bypasses the normal Super Admin user-management
page.
"""

import argparse
import getpass
import os
from pathlib import Path

from webmanager.storage import Store


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover a SNTalkBot Web Manager account password")
    parser.add_argument(
        "--db",
        default=os.getenv("SNWEB_DB_FILE", "/var/lib/sntalkbot-web-manager/webmanager.db"),
        help="SQLite database path (default: SNWEB_DB_FILE or /var/lib/sntalkbot-web-manager/webmanager.db)",
    )
    parser.add_argument("--username", default=os.getenv("SNWEB_ADMIN_USER", "admin"))
    parser.add_argument("--display-name", default="")
    parser.add_argument("--password", default=os.getenv("SNWEB_ADMIN_PASSWORD"))
    args = parser.parse_args()

    password = args.password or getpass.getpass("New password: ")
    if len(password) < 10:
        raise SystemExit("Password must be at least 10 characters")

    db_path = Path(args.db)
    store = Store(db_path)
    existing = store.get_user_by_username(args.username)
    if existing:
        store.set_password(int(existing["id"]), password)
        print(f"Password reset for {existing['username']} in {db_path}")
        return 0

    if store.user_count() == 0:
        user = store.create_first_superadmin(args.username, password, display_name=args.display_name)
        if not user:
            raise SystemExit("Failed to create the first Super Admin")
        print(f"Created first Super Admin {user['username']} in {db_path}")
        return 0

    raise SystemExit(
        "Account not found. For safety this recovery tool will not create an additional account after first-run setup; "
        "sign in as Super Admin and use the Users page instead."
    )


if __name__ == "__main__":
    raise SystemExit(main())
