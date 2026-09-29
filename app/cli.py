"""Create the first administrator account.

Registration deliberately cannot grant admin, so a fresh install needs a way to
get one. This is a local CLI rather than an endpoint: no HTTP surface can mint
an admin, which keeps the privilege escalation path out of the API entirely.

Usage:
    python -m app.cli create-admin --email admin@example.com
    python -m app.cli grant-admin --email someone@example.com
    python -m app.cli list-users
    python -m app.cli enrich-securities [--limit N] [--restart]
"""

from __future__ import annotations

import argparse
import getpass
import logging
import sys

from sqlalchemy import select

from app.auth.security import PasswordPolicyError, make_password_record
from app.db.models import User
from app.db.session import init_db, session_scope

logger = logging.getLogger("app.cli")


def _read_password(use_flag: str | None) -> str:
    """Read the password from a flag or an interactive prompt.

    The prompt refuses to echo, so a password typed at the terminal does not
    end up in shell history or a scrollback buffer.
    """
    if use_flag:
        return use_flag
    return getpass.getpass("Password: ")


def create_admin(email: str, password_flag: str | None) -> int:
    init_db()
    with session_scope() as session:
        if session.scalar(select(User).where(User.email == email)) is not None:
            print(f"{email} already exists.", file=sys.stderr)
            return 1
        try:
            salt, digest = make_password_record(_read_password(password_flag))
        except PasswordPolicyError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        session.add(
            User(
                email=email,
                password_salt=salt,
                password_hash=digest,
                is_admin=True,
                is_active=True,
            )
        )
    print(f"Created administrator {email}.")
    return 0


def grant_admin(email: str) -> int:
    with session_scope() as session:
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"No such account: {email}", file=sys.stderr)
            return 1
        # Existing tokens were issued without admin scope checks, so bump the
        # version to keep the change from being half-applied to a live session.
        user.is_admin = True
        user.token_version += 1
    print(f"{email} is now an administrator. Existing sessions were invalidated.")
    return 0


def list_users() -> int:
    with session_scope() as session:
        users = session.scalars(select(User).order_by(User.created_at)).all()
        if not users:
            print("No accounts yet.")
            return 0
        for user in users:
            flags = [f"admin" if user.is_admin else "user"]
            if not user.is_active:
                flags.append("disabled")
            print(f"{user.email:<32} {'/'.join(flags):<16} created {user.created_at:%Y-%m-%d}")
    return 0


def enrich_securities(limit: int | None, restart: bool) -> int:
    """Bulk-fetch listed shares so market cap (shares x LTP) can be derived.

    NEPSE publishes `stockListedShares` only on the per-security detail
    endpoint, not in the security master, so every security needs one call
    before market-cap views are meaningful. Resumable: re-running skips
    symbols that already have the value.
    """
    import asyncio

    from app.db.session import session_scope as _scope
    from app.nepse.registry import close_adapter, start_adapter
    from app.reference.service import ReferenceService

    async def run() -> dict:
        adapter = await start_adapter()
        service = ReferenceService(adapter)
        try:
            with _scope() as session:
                return await service.enrich_missing_listed_shares(
                    session, limit=limit, resume=not restart
                )
        finally:
            await close_adapter()

    print("Fetching listed shares from NEPSE (this is paced; please wait)...", flush=True)
    summary = asyncio.run(run())
    print(
        f"Attempted {summary['attempted']}, enriched {summary['enriched']}, "
        f"failed {len(summary['failed'])}."
    )
    print(
        f"Still missing listed shares: "
        f"{summary['remaining_without_listed_shares']}."
    )
    if summary["failed"]:
        preview = ", ".join(summary["failed"][:20])
        more = "" if len(summary["failed"]) <= 20 else f" (+{len(summary['failed']) - 20} more)"
        print(f"Could not enrich: {preview}{more}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-admin", help="Create an administrator account")
    create.add_argument("--email", required=True)
    create.add_argument(
        "--password",
        help="Password. Omit to be prompted without echo; only use this in CI.",
    )

    grant = sub.add_parser("grant-admin", help="Promote an existing account to admin")
    grant.add_argument("--email", required=True)

    sub.add_parser("list-users", help="List accounts and their roles")

    enrich = sub.add_parser(
        "enrich-securities",
        help="Bulk-fetch listed shares so market cap can be derived",
    )
    enrich.add_argument(
        "--limit", type=int, default=None, help="Only enrich the first N missing symbols"
    )
    enrich.add_argument(
        "--restart",
        action="store_true",
        help="Re-enrich every symbol instead of only the missing ones",
    )

    args = parser.parse_args(argv)
    if args.command == "create-admin":
        return create_admin(args.email, args.password)
    if args.command == "grant-admin":
        return grant_admin(args.email)
    if args.command == "enrich-securities":
        return enrich_securities(args.limit, args.restart)
    return list_users()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    raise SystemExit(main())
