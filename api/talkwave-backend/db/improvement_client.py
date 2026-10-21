from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import WorkflowImprovementModel, WorkflowRunModel


class ImprovementClient(BaseDBClient):
    async def create_improvement(
        self,
        workflow_id: int,
        organization_id: int,
        suggestions: list,
        analysis_summary: str,
        calls_analyzed: int,
        last_run_id_analyzed: int,
    ) -> WorkflowImprovementModel:
        async with self.async_session() as session:
            improvement = WorkflowImprovementModel(
                workflow_id=workflow_id,
                organization_id=organization_id,
                suggestions=suggestions,
                analysis_summary=analysis_summary,
                calls_analyzed=calls_analyzed,
                last_run_id_analyzed=last_run_id_analyzed,
                status="pending",
            )
            session.add(improvement)
            await session.commit()
            await session.refresh(improvement)
            return improvement

    async def get_improvements_for_workflow(
        self,
        workflow_id: int,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> List[WorkflowImprovementModel]:
        async with self.async_session() as session:
            q = select(WorkflowImprovementModel).where(
                WorkflowImprovementModel.workflow_id == workflow_id
            )
            if status:
                q = q.where(WorkflowImprovementModel.status == status)
            q = q.order_by(WorkflowImprovementModel.created_at.desc()).limit(limit)
            result = await session.execute(q)
            return list(result.scalars().all())

    async def get_improvement_by_id(
        self, improvement_id: int
    ) -> Optional[WorkflowImprovementModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(WorkflowImprovementModel).where(
                    WorkflowImprovementModel.id == improvement_id
                )
            )
            return result.scalars().first()

    async def update_improvement_status(
        self, improvement_id: int, status: str
    ) -> Optional[WorkflowImprovementModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(WorkflowImprovementModel).where(
                    WorkflowImprovementModel.id == improvement_id
                )
            )
            improvement = result.scalars().first()
            if not improvement:
                return None
            improvement.status = status
            await session.commit()
            await session.refresh(improvement)
            return improvement

    async def update_improvement_decision(
        self,
        improvement_id: int,
        applied_indices: List[int],
        rejected_indices: List[int],
    ) -> Optional[WorkflowImprovementModel]:
        """Persist per-suggestion accept/reject indices on an improvement batch."""
        async with self.async_session() as session:
            result = await session.execute(
                select(WorkflowImprovementModel).where(
                    WorkflowImprovementModel.id == improvement_id
                )
            )
            improvement = result.scalars().first()
            if not improvement:
                return None
            # Force SQLAlchemy to detect the JSON column change by reassigning a
            # fresh list (mutating in place doesn't trip the change tracker).
            improvement.applied_indices = list(applied_indices or [])
            improvement.rejected_indices = list(rejected_indices or [])
            await session.commit()
            await session.refresh(improvement)
            return improvement

    async def get_last_analyzed_run_id(self, workflow_id: int) -> Optional[int]:
        """Get the last_run_id_analyzed from the most recent analysis for a workflow."""
        async with self.async_session() as session:
            result = await session.execute(
                select(WorkflowImprovementModel.last_run_id_analyzed)
                .where(WorkflowImprovementModel.workflow_id == workflow_id)
                .order_by(WorkflowImprovementModel.created_at.desc())
                .limit(1)
            )
            row = result.scalars().first()
            return row

    async def count_completed_runs_since(
        self, workflow_id: int, since_run_id: Optional[int] = None
    ) -> int:
        """Count completed runs for a workflow since a given run ID."""
        async with self.async_session() as session:
            q = select(func.count(WorkflowRunModel.id)).where(
                WorkflowRunModel.workflow_id == workflow_id,
                WorkflowRunModel.is_completed == True,
            )
            if since_run_id:
                q = q.where(WorkflowRunModel.id > since_run_id)
            result = await session.execute(q)
            return result.scalar() or 0

    async def get_recent_completed_runs(
        self,
        workflow_id: int,
        since_run_id: Optional[int] = None,
        limit: int = 20,
    ) -> List[WorkflowRunModel]:
        """Load recent completed runs with minimal data for analysis."""
        async with self.async_session() as session:
            q = select(WorkflowRunModel).where(
                WorkflowRunModel.workflow_id == workflow_id,
                WorkflowRunModel.is_completed == True,
            )
            if since_run_id:
                q = q.where(WorkflowRunModel.id > since_run_id)
            q = q.order_by(WorkflowRunModel.id.desc()).limit(limit)
            result = await session.execute(q)
            return list(result.scalars().all())

    async def get_pending_improvement_count(self, workflow_id: int) -> int:
        async with self.async_session() as session:
            result = await session.execute(
                select(func.count(WorkflowImprovementModel.id)).where(
                    WorkflowImprovementModel.workflow_id == workflow_id,
                    WorkflowImprovementModel.status == "pending",
                )
            )
            return result.scalar() or 0
