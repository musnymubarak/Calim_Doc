"""Shared API dependencies: current user + arq pool.

NOTE: auth is a dev stub. A single shared Gemini key is used server-side, but users are
still isolated for storage/quotas. Replace `get_current_user` with real auth before launch.
"""
from __future__ import annotations

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db
from app.models.user import User


async def get_current_user(
    x_user_email: str = Header(default="dev@local"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dev stub: resolve (or create) a user from the X-User-Email header."""
    result = await db.execute(select(User).where(User.email == x_user_email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=x_user_email)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def get_arq_pool() -> ArqRedis:
    return await create_pool(RedisSettings.from_dsn(settings.redis_url))
