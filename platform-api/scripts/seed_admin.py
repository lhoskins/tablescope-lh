"""Seed a default tenant and admin user for local/testing use.

Usage:
    python -m scripts.seed_admin [--email EMAIL] [--password PASSWORD] [--tenant-slug SLUG]

Defaults:
    email:       admin@tablescope.local
    password:    admin
    tenant-slug: default
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.tenant import Tenant
from app.models.user import User


async def seed(email: str, password: str, tenant_slug: str) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        async with session.begin():
            tenant = await session.scalar(
                select(Tenant).where(Tenant.slug == tenant_slug)
            )
            if tenant is None:
                tenant = Tenant(slug=tenant_slug, name=tenant_slug.title())
                session.add(tenant)
                await session.flush()
                print(f"Created tenant: {tenant_slug} (id={tenant.id})")
            else:
                print(f"Tenant already exists: {tenant_slug} (id={tenant.id})")

            user = await session.scalar(
                select(User).where(
                    User.email == email, User.tenant_id == tenant.id
                )
            )
            if user is None:
                user = User(
                    tenant_id=tenant.id,
                    email=email,
                    display_name="Admin",
                    role="admin",
                    external_id=f"local:{email}",
                )
                user.set_password(password)
                session.add(user)
                await session.flush()
                print(f"Created admin user: {email} (id={user.id})")
            else:
                user.set_password(password)
                print(f"Admin user already exists: {email} (id={user.id}) — password updated")

    await engine.dispose()
    print("\nLogin credentials:")
    print(f"  Email:    {email}")
    print(f"  Password: {password}")
    print(f"  Tenant:   {tenant_slug}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed admin user")
    parser.add_argument("--email", default="admin@tablescope.local")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--tenant-slug", default="default")
    args = parser.parse_args()
    asyncio.run(seed(args.email, args.password, args.tenant_slug))


if __name__ == "__main__":
    main()
