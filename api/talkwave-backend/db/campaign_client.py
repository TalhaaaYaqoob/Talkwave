from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import delete as sa_delete, func, text, update as sa_update
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import CampaignModel, QueuedRunModel, WorkflowRunModel


class CampaignClient(BaseDBClient):
    async def create_campaign(
        self,
        name: str,
        workflow_id: int,
        source_type: str,
        source_id: str,
        user_id: int,
        organization_id: int,
        scheduled_start_at=None,
        calling_window_start: str | None = None,
        calling_window_end: str | None = None,
        calling_window_timezone: str | None = None,
    ) -> CampaignModel:
        """Create a new campaign"""
        async with self.async_session() as session:
            campaign = CampaignModel(
                name=name,
                workflow_id=workflow_id,
                source_type=source_type,
                source_id=source_id,
                created_by=user_id,
                organization_id=organization_id,
                scheduled_start_at=scheduled_start_at,
                calling_window_start=calling_window_start,
                calling_window_end=calling_window_end,
                calling_window_timezone=calling_window_timezone or "UTC",
            )
            session.add(campaign)
            try:
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise e
            await session.refresh(campaign)
            return campaign

    async def get_campaigns(
        self,
        organization_id: int,
    ) -> list[CampaignModel]:
        """Get all campaigns for organization"""
        async with self.async_session() as session:
            query = (
                select(CampaignModel)
                .where(CampaignModel.organization_id == organization_id)
                .order_by(CampaignModel.created_at.desc())
            )

            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_campaign(
        self,
        campaign_id: int,
        organization_id: int,
    ) -> Optional[CampaignModel]:
        """Get single campaign by ID, ensuring organization access"""
        async with self.async_session() as session:
            query = select(CampaignModel).where(
                CampaignModel.id == campaign_id,
                CampaignModel.organization_id == organization_id,
            )
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def delete_campaign(
        self,
        campaign_id: int,
        organization_id: int,
    ) -> bool:
        """Delete a campaign and its queued runs. Only allowed for non-running campaigns."""
        async with self.async_session() as session:
            campaign = (
                await session.execute(
                    select(CampaignModel).where(
                        CampaignModel.id == campaign_id,
                        CampaignModel.organization_id == organization_id,
                    )
                )
            ).scalar_one_or_none()

            if not campaign:
                return False

            if campaign.state == "running":
                raise ValueError("Cannot delete a running campaign. Pause it first.")

            # Nullify foreign key references from workflow_runs to queued_runs
            await session.execute(
                sa_update(WorkflowRunModel)
                .where(WorkflowRunModel.campaign_id == campaign_id)
                .values(queued_run_id=None)
            )

            # Delete associated queued runs
            await session.execute(
                sa_delete(QueuedRunModel).where(QueuedRunModel.campaign_id == campaign_id)
            )

            # Delete associated workflow runs
            await session.execute(
                sa_delete(WorkflowRunModel).where(WorkflowRunModel.campaign_id == campaign_id)
            )

            await session.delete(campaign)
            await session.commit()
            return True

    async def update_campaign_state(
        self,
        campaign_id: int,
        state: str,
        organization_id: int,
    ) -> CampaignModel:
        """Update campaign state (start/pause/resume)"""
        async with self.async_session() as session:
            query = select(CampaignModel).where(
                CampaignModel.id == campaign_id,
                CampaignModel.organization_id == organization_id,
            )
            result = await session.execute(query)
            campaign = result.scalar_one_or_none()

            if not campaign:
                raise ValueError(f"Campaign {campaign_id} not found")

            campaign.state = state
            if state == "running" and not campaign.started_at:
                campaign.started_at = datetime.now(UTC)
            elif state in ["completed", "failed"]:
                campaign.completed_at = datetime.now(UTC)

            try:
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise e
            await session.refresh(campaign)
            return campaign

    async def update_campaign_progress(
        self,
        campaign_id: int,
        processed_rows: int,
        failed_rows: int,
        organization_id: int,
    ) -> None:
        """Update campaign progress counters"""
        async with self.async_session() as session:
            query = select(CampaignModel).where(
                CampaignModel.id == campaign_id,
                CampaignModel.organization_id == organization_id,
            )
            result = await session.execute(query)
            campaign = result.scalar_one_or_none()

            if not campaign:
                raise ValueError(f"Campaign {campaign_id} not found")

            campaign.processed_rows = processed_rows
            campaign.failed_rows = failed_rows
            campaign.updated_at = datetime.now(UTC)

            try:
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise e

    async def get_campaign_runs(
        self,
        campaign_id: int,
        organization_id: int,
    ) -> list[WorkflowRunModel]:
        """Get workflow runs for a campaign"""
        async with self.async_session() as session:
            # First verify campaign belongs to organization
            campaign_query = select(CampaignModel).where(
                CampaignModel.id == campaign_id,
                CampaignModel.organization_id == organization_id,
            )
            campaign_result = await session.execute(campaign_query)
            campaign = campaign_result.scalar_one_or_none()

            if not campaign:
                raise ValueError(f"Campaign {campaign_id} not found")

            query = (
                select(WorkflowRunModel)
                .where(WorkflowRunModel.campaign_id == campaign_id)
                .order_by(WorkflowRunModel.created_at.desc())
            )

            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_campaign_by_id(self, campaign_id: int) -> Optional[CampaignModel]:
        """Get campaign by ID without organization check (for internal use)"""
        async with self.async_session() as session:
            query = select(CampaignModel).where(CampaignModel.id == campaign_id)
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def update_campaign(self, campaign_id: int, **kwargs) -> CampaignModel:
        """Update campaign with arbitrary fields"""
        async with self.async_session() as session:
            query = select(CampaignModel).where(CampaignModel.id == campaign_id)
            result = await session.execute(query)
            campaign = result.scalar_one_or_none()

            if not campaign:
                raise ValueError(f"Campaign {campaign_id} not found")

            # Update fields
            for key, value in kwargs.items():
                if hasattr(campaign, key):
                    setattr(campaign, key, value)

            campaign.updated_at = datetime.now(UTC)

            try:
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise e
            await session.refresh(campaign)
            return campaign

    # QueuedRun methods
    async def bulk_create_queued_runs(self, queued_runs_data: list[dict]) -> None:
        """Bulk create queued runs"""
        async with self.async_session() as session:
            queued_runs = [QueuedRunModel(**data) for data in queued_runs_data]
            session.add_all(queued_runs)
            try:
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise e

    async def get_queued_runs(
        self,
        campaign_id: int,
        state: str = "queued",
        limit: int = 10,
        scheduled_for: Optional[bool] = None,
    ) -> list[QueuedRunModel]:
        """Get queued runs for processing, optionally filtering by scheduled status"""
        async with self.async_session() as session:
            query = select(QueuedRunModel).where(
                QueuedRunModel.campaign_id == campaign_id,
                QueuedRunModel.state == state,
            )

            # Filter by scheduled status if specified
            if scheduled_for is True:
                query = query.where(QueuedRunModel.scheduled_for.isnot(None))
            elif scheduled_for is False:
                query = query.where(QueuedRunModel.scheduled_for.is_(None))

            query = query.order_by(QueuedRunModel.created_at).limit(limit)

            result = await session.execute(query)
            return list(result.scalars().all())

    async def update_queued_run(self, queued_run_id: int, **kwargs) -> QueuedRunModel:
        """Update queued run"""
        async with self.async_session() as session:
            query = select(QueuedRunModel).where(QueuedRunModel.id == queued_run_id)
            result = await session.execute(query)
            queued_run = result.scalar_one_or_none()

            if not queued_run:
                raise ValueError(f"QueuedRun {queued_run_id} not found")

            # Update fields
            for key, value in kwargs.items():
                if hasattr(queued_run, key):
                    setattr(queued_run, key, value)

            try:
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise e
            await session.refresh(queued_run)
            return queued_run

    async def count_queued_runs(
        self, campaign_id: int, state: Optional[str] = None
    ) -> int:
        """Count queued runs, optionally filtered by state"""
        async with self.async_session() as session:
            query = select(func.count(QueuedRunModel.id)).where(
                QueuedRunModel.campaign_id == campaign_id
            )
            if state:
                query = query.where(QueuedRunModel.state == state)

            result = await session.execute(query)
            return result.scalar() or 0

    async def get_workflow_runs_by_campaign(
        self, campaign_id: int
    ) -> list[WorkflowRunModel]:
        """Get all workflow runs for a campaign (internal use)"""
        async with self.async_session() as session:
            query = (
                select(WorkflowRunModel)
                .where(WorkflowRunModel.campaign_id == campaign_id)
                .order_by(WorkflowRunModel.created_at)
            )
            result = await session.execute(query)
            return list(result.scalars().all())

    # New methods for retry support
    async def get_scheduled_queued_runs(
        self, campaign_id: int, scheduled_before: datetime, limit: int = 10
    ) -> list[QueuedRunModel]:
        """Get scheduled queued runs that are due for processing"""
        async with self.async_session() as session:
            query = (
                select(QueuedRunModel)
                .where(
                    QueuedRunModel.campaign_id == campaign_id,
                    QueuedRunModel.state == "queued",
                    QueuedRunModel.scheduled_for.isnot(None),
                    QueuedRunModel.scheduled_for <= scheduled_before,
                )
                .order_by(QueuedRunModel.scheduled_for)
                .limit(limit)
            )
            result = await session.execute(query)
            return list(result.scalars().all())

    async def create_queued_run(
        self,
        campaign_id: int,
        source_uuid: str,
        context_variables: dict,
        state: str = "queued",
        retry_count: int = 0,
        parent_queued_run_id: Optional[int] = None,
        scheduled_for: Optional[datetime] = None,
        retry_reason: Optional[str] = None,
    ) -> QueuedRunModel:
        """Create a single queued run with retry support"""
        async with self.async_session() as session:
            queued_run = QueuedRunModel(
                campaign_id=campaign_id,
                source_uuid=source_uuid,
                context_variables=context_variables,
                state=state,
                retry_count=retry_count,
                parent_queued_run_id=parent_queued_run_id,
                scheduled_for=scheduled_for,
                retry_reason=retry_reason,
            )
            session.add(queued_run)
            try:
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise e
            await session.refresh(queued_run)
            return queued_run

    async def get_queued_run_by_id(
        self, queued_run_id: int
    ) -> Optional[QueuedRunModel]:
        """Get a queued run by ID"""
        async with self.async_session() as session:
            query = select(QueuedRunModel).where(QueuedRunModel.id == queued_run_id)
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def get_campaigns_by_status(self, statuses: list[str]) -> list[CampaignModel]:
        """Get campaigns by status"""
        async with self.async_session() as session:
            query = (
                select(CampaignModel)
                .where(CampaignModel.state.in_(statuses))
                .order_by(CampaignModel.created_at.desc())
            )
            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_queued_runs_count(self, campaign_id: int, states: list[str]) -> int:
        """Get count of queued runs for a campaign in specified states"""
        async with self.async_session() as session:
            query = select(func.count(QueuedRunModel.id)).where(
                QueuedRunModel.campaign_id == campaign_id,
                QueuedRunModel.state.in_(states),
            )
            result = await session.execute(query)
            return result.scalar() or 0

    async def get_scheduled_runs_count(
        self,
        campaign_id: int,
        scheduled_before: Optional[datetime] = None,
        scheduled_after: Optional[datetime] = None,
    ) -> int:
        """Get count of scheduled runs for a campaign"""
        async with self.async_session() as session:
            conditions = [
                QueuedRunModel.campaign_id == campaign_id,
                QueuedRunModel.scheduled_for.isnot(None),
                QueuedRunModel.state == "queued",
            ]

            if scheduled_before:
                conditions.append(QueuedRunModel.scheduled_for <= scheduled_before)
            if scheduled_after:
                conditions.append(QueuedRunModel.scheduled_for > scheduled_after)

            query = select(func.count(QueuedRunModel.id)).where(*conditions)
            result = await session.execute(query)
            return result.scalar() or 0

    async def get_campaign_analytics(
        self,
        campaign_id: int,
        organization_id: int,
    ) -> dict:
        """Compute analytics for a single campaign from workflow_runs data."""
        async with self.async_session() as session:
            campaign_q = select(CampaignModel).where(
                CampaignModel.id == campaign_id,
                CampaignModel.organization_id == organization_id,
            )
            campaign_result = await session.execute(campaign_q)
            campaign = campaign_result.scalar_one_or_none()
            if not campaign:
                raise ValueError(f"Campaign {campaign_id} not found")

            runs_q = select(WorkflowRunModel).where(
                WorkflowRunModel.campaign_id == campaign_id,
            )
            result = await session.execute(runs_q)
            workflow_runs = list(result.scalars().all())

            disposition_counts: dict[str, int] = {}
            total_duration = 0.0
            connected_count = 0
            durations: list[float] = []

            for wr in workflow_runs:
                callbacks = (wr.logs or {}).get("telephony_status_callbacks", [])
                disposition = callbacks[-1].get("status") if callbacks else "unknown"
                disposition_counts[disposition] = disposition_counts.get(disposition, 0) + 1

                usage = wr.usage_info or {}
                dur = usage.get("total_call_duration", 0) or 0
                if dur > 0:
                    connected_count += 1
                    total_duration += dur
                    durations.append(dur)

            avg_duration = (total_duration / len(durations)) if durations else 0

            return {
                "total_contacts": campaign.total_rows or 0,
                "processed": campaign.processed_rows,
                "failed": campaign.failed_rows,
                "remaining": max(
                    0,
                    (campaign.total_rows or 0)
                    - campaign.processed_rows
                    - campaign.failed_rows,
                ),
                "connected_calls": connected_count,
                "total_calls_made": len(workflow_runs),
                "avg_call_duration": round(avg_duration, 1),
                "total_call_duration": round(total_duration, 1),
                "disposition_breakdown": disposition_counts,
                "durations": sorted(durations),
            }

    async def get_connected_calls_counts(
        self,
        campaign_ids: list[int],
    ) -> dict[int, int]:
        """Count calls where total_call_duration > 0 (someone actually picked up)."""
        if not campaign_ids:
            return {}
        async with self.async_session() as session:
            query = (
                select(
                    WorkflowRunModel.campaign_id,
                    func.count(WorkflowRunModel.id),
                )
                .where(
                    WorkflowRunModel.campaign_id.in_(campaign_ids),
                    WorkflowRunModel.campaign_id.isnot(None),
                    text(
                        "COALESCE("
                        "(workflow_runs.usage_info->>'total_call_duration')::float, 0"
                        ") > 0"
                    ),
                )
                .group_by(WorkflowRunModel.campaign_id)
            )
            result = await session.execute(query)
            return dict(result.all())

    async def get_campaign_contacts(
        self,
        campaign_id: int,
        organization_id: int,
        status_filter: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict], int]:
        """Get enriched contact data for a campaign by joining queued_runs with workflow_runs.

        Returns a tuple of (contacts_list, total_count).
        """
        from sqlalchemy.orm import selectinload

        async with self.async_session() as session:
            # Verify campaign belongs to organization
            campaign_q = select(CampaignModel).where(
                CampaignModel.id == campaign_id,
                CampaignModel.organization_id == organization_id,
            )
            campaign_result = await session.execute(campaign_q)
            campaign = campaign_result.scalar_one_or_none()
            if not campaign:
                raise ValueError(f"Campaign {campaign_id} not found")

            # Base conditions – exclude retry entries (parent_queued_run_id IS NULL)
            conditions = [
                QueuedRunModel.campaign_id == campaign_id,
                QueuedRunModel.parent_queued_run_id.is_(None),
            ]
            if status_filter and status_filter in ("queued", "processed", "failed"):
                conditions.append(QueuedRunModel.state == status_filter)

            # Total count
            count_q = select(func.count(QueuedRunModel.id)).where(*conditions)
            count_result = await session.execute(count_q)
            total_count = count_result.scalar() or 0

            # Fetch queued runs with pagination
            runs_q = (
                select(QueuedRunModel)
                .where(*conditions)
                .order_by(QueuedRunModel.id)
                .offset(offset)
                .limit(limit)
            )
            runs_result = await session.execute(runs_q)
            queued_runs = list(runs_result.scalars().all())

            if not queued_runs:
                return [], total_count

            # Get linked workflow runs for these queued runs
            qr_ids = [qr.id for qr in queued_runs]
            wr_q = select(WorkflowRunModel).where(
                WorkflowRunModel.queued_run_id.in_(qr_ids)
            )
            wr_result = await session.execute(wr_q)
            workflow_runs = list(wr_result.scalars().all())
            wr_map = {wr.queued_run_id: wr for wr in workflow_runs}

            # Build enriched contact list
            contacts = []
            for qr in queued_runs:
                ctx = qr.context_variables or {}
                wr = wr_map.get(qr.id)

                # Determine call disposition from workflow run
                disposition = None
                call_duration = None
                if wr:
                    callbacks = (wr.logs or {}).get("telephony_status_callbacks", [])
                    if callbacks:
                        disposition = callbacks[-1].get("status", None)
                    usage = wr.usage_info or {}
                    call_duration = usage.get("total_call_duration", None)

                contacts.append({
                    "id": qr.id,
                    "phone_number": ctx.get("phone_number", ""),
                    "first_name": ctx.get("first_name", ""),
                    "last_name": ctx.get("last_name", ""),
                    "status": qr.state,
                    "disposition": disposition,
                    "call_duration": call_duration,
                    "retry_count": qr.retry_count,
                    "retry_reason": qr.retry_reason,
                    "created_at": qr.created_at.isoformat() if qr.created_at else None,
                    "processed_at": qr.processed_at.isoformat() if qr.processed_at else None,
                    "workflow_run_id": wr.id if wr else None,
                })

            return contacts, total_count
