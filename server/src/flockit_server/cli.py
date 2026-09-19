"""``flockit-server`` command line: serve, migrate, create an admin, load demo data."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path
from typing import List, Optional

from alembic import command
from alembic.config import Config

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def alembic_config(url: Optional[str] = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    if url:
        cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def migrate(url: Optional[str] = None) -> None:
    command.upgrade(alembic_config(url), "head")


async def _create_admin(email: str, name: str, password: str, org_name: str) -> None:
    from sqlalchemy import select

    from flockit_server import db
    from flockit_server.models import Organization, Role, User
    from flockit_server.security import hash_password

    async with db.sessionmaker()() as session:
        org = (await session.execute(select(Organization).limit(1))).scalar_one_or_none()
        if org is None:
            org = Organization(name=org_name)
            session.add(org)
            await session.flush()
        existing = (await session.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
        if existing:
            existing.role = Role.admin
            existing.password_hash = hash_password(password)
            existing.is_active = True
        else:
            session.add(
                User(org_id=org.id, email=email.lower(), name=name, role=Role.admin, password_hash=hash_password(password))
            )
        await session.commit()
    await db.dispose()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="flockit-server")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="run migrations, then serve the API and web UI")
    p.add_argument("--host", default=os.environ.get("FLOCKIT_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.environ.get("FLOCKIT_PORT", "8080")))
    p.add_argument("--no-migrate", action="store_true")

    sub.add_parser("migrate", help="apply database migrations")

    p = sub.add_parser("revision", help="autogenerate a migration from model changes (development)")
    p.add_argument("-m", "--message", required=True)

    p = sub.add_parser("create-admin", help="create an admin, or reset an existing user to admin")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="Admin")
    p.add_argument("--org", default="My organisation")
    p.add_argument("--password", help="omit to be prompted")

    p = sub.add_parser("seed-demo", help="load a demo organisation with realistic sessions (empty database only)")
    p.add_argument("--days", type=int, default=14)

    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        if not args.no_migrate:
            migrate()
        uvicorn.run(
            "flockit_server.main:app",
            host=args.host,
            port=args.port,
            proxy_headers=True,
            forwarded_allow_ips=os.environ.get("FLOCKIT_FORWARDED_ALLOW_IPS", "127.0.0.1"),
            access_log=False,
        )
        return 0
    if args.command == "migrate":
        migrate()
        print("Database is up to date.")
        return 0
    if args.command == "revision":
        command.revision(alembic_config(), message=args.message, autogenerate=True)
        return 0
    if args.command == "create-admin":
        password = args.password or getpass.getpass("Password for %s: " % args.email)
        if len(password) < 8:
            print("Use at least 8 characters.", file=sys.stderr)
            return 2
        asyncio.run(_create_admin(args.email, args.name, password, args.org))
        print("Admin %s is ready." % args.email)
        return 0
    if args.command == "seed-demo":
        from flockit_server.demo import seed

        return asyncio.run(seed(days=args.days))
    return 1


if __name__ == "__main__":
    sys.exit(main())
