"""Collector tokens. Each person manages their own; a token is shown exactly once."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flockit_server.db import get_db
from flockit_server.deps import current_user
from flockit_server.models import ApiToken, User
from flockit_server.schemas import TokenCreated, TokenIn, TokenOut
from flockit_server.security import new_collector_token

router = APIRouter(prefix="/api/tokens", tags=["tokens"])


def _out(t: ApiToken) -> TokenOut:
    return TokenOut(
        id=t.id, name=t.name, kind=t.kind, prefix=t.prefix, created_at=t.created_at, last_used_at=t.last_used_at
    )


@router.get("", response_model=List[TokenOut])
async def list_tokens(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(ApiToken)
        .where(ApiToken.user_id == user.id, ApiToken.revoked_at.is_(None), ApiToken.run_id.is_(None))
        .order_by(ApiToken.created_at.desc())
    )
    return [_out(t) for t in rows.scalars()]


@router.post("", response_model=TokenCreated, status_code=201)
async def create_token(body: TokenIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if body.kind not in ("collector", "mcp"):
        raise HTTPException(422, "kind must be collector or mcp")
    token, prefix, token_hash = new_collector_token()
    row = ApiToken(
        org_id=user.org_id, user_id=user.id, name=body.name.strip(), kind=body.kind, prefix=prefix, token_hash=token_hash
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return TokenCreated(**_out(row).model_dump(), token=token)


@router.delete("/{token_id}", status_code=204)
async def revoke_token(token_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    row = (
        await db.execute(select(ApiToken).where(ApiToken.id == token_id, ApiToken.user_id == user.id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Token not found")
    row.revoked_at = datetime.now(timezone.utc)
    await db.commit()
