from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from flockit_server.db import get_db
from flockit_server.deps import CollectorIdentity, collector_identity
from flockit_server.ingest import ingest
from flockit_server.schemas import IngestBatch, IngestResult

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


@router.post("/events", response_model=IngestResult)
async def post_events(
    batch: IngestBatch,
    who: CollectorIdentity = Depends(collector_identity),
    db: AsyncSession = Depends(get_db),
) -> IngestResult:
    return await ingest(db, who.user, batch.events)


@router.get("/whoami")
async def whoami(who: CollectorIdentity = Depends(collector_identity)) -> dict:
    """Used by ``flockit install`` and ``flockit status`` to check the token."""
    return {"user": {"id": str(who.user.id), "name": who.user.name, "email": who.user.email}}
