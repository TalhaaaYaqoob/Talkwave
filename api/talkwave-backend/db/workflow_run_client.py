from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import cast, func, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.orm.attributes import flag_modified

from api.db.base_client import BaseDBClient
from api.db.filters import apply_workflow_run_filters
from api.db.models import (
    OrganizationModel,
    UserModel,
    WorkflowDefinitionModel,
    WorkflowModel,
    WorkflowRunModel,
)
from api.enums import StorageBackend
from api.schemas.workflow import WorkflowRunResponseSchema


class WorkflowRunClient(BaseDBClient):
    async def create_workflow_run(
        self,
        name: str,
        workflow_id: int,
        mode: str,
        user_id: int,
        initial_context: dict = None,
        campaign_id: int = None,
        queued_run_id: int = None,
        gathered_context: dict = None,
    ) -> WorkflowRunModel:
        async with self.async_session() as session:
            # Get workflow and user to check organization
            workflow = await session.execute(
                select(WorkflowModel)
                .options(joinedload(WorkflowModel.user))
                .where(
                    WorkflowModel.id == workflow_id, WorkflowModel.user_id == user_id
                )
            )
            workflow = workflow.scalars().first()
            if not workflow:
                raise ValueError(f"Workflow with ID {workflow_id} not found")

            # Fetch the current definition for this workflow
            current_def_result = await session.execute(
                select(WorkflowDefinitionModel).where(
                    WorkflowDefinitionModel.workflow_id == workflow.id,
                    WorkflowDefinitionModel.is_current == True,
                )
            )
            current_def = current_def_result.scalars().first()

            # Get the current storage backend based on ENABLE_AWS_S3 flag
            current_backend = StorageBackend.get_current_backend()

            new_run = WorkflowRunModel(
                name=name,
                workflow=workflow,
                mode=mode,
                definition_id=current_def.id if current_def else None,
                initial_context=initial_context or workflow.template_context_variables,
                gathered_context=gathered_context or {},
                campaign_id=campaign_id,
                queued_run_id=queued_run_id,
                storage_backend=current_backend.value,
            )
            session.add(new_run)
            try:
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise e
            await session.refresh(new_run)
        return new_run

    async def get_all_workflow_runs(self) -> list[WorkflowRunModel]:
        async with self.async_session() as session:
            result = await session.execute(select(WorkflowRunModel))
            return result.scalars().all()

    async def get_workflow_runs_for_superadmin(
        self,
        limit: int = 50,
        offset: int = 0,
        filters: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[list[dict], int]:
        """
        Get paginated workflow runs for superadmin with organization information.
        Returns tuple of (workflow_runs, total_count).
        """
        async with self.async_session() as session:
            # Build base query with joins
            base_query = (
                select(WorkflowRunModel)
                .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                .join(UserModel, WorkflowModel.user_id == UserModel.id)
                .outerjoin(
                    OrganizationModel,
                    UserModel.selected_organization_id == OrganizationModel.id,
                )
            )

            # Apply filters
            base_query = apply_workflow_run_filters(base_query, filters)

            # Count total with filters
            count_query = base_query.with_only_columns(func.count(WorkflowRunModel.id))
            count_result = await session.execute(count_query)
            total_count = count_result.scalar()

            # Get paginated results with filters
            result = await session.execute(
                base_query.options(
                    joinedload(WorkflowRunModel.workflow).joinedload(
                        WorkflowModel.user
                    ),
                    joinedload(WorkflowRunModel.workflow)
                    .joinedload(WorkflowModel.user)
                    .joinedload(UserModel.selected_organization),
                )
                .order_by(WorkflowRunModel.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            workflow_runs = result.scalars().all()

            # Format the response
            formatted_runs = []
            for run in workflow_runs:
                organization = (
                    run.workflow.user.selected_organization
                    if run.workflow.user
                    else None
                )
                formatted_runs.append(
                    {
                        "id": run.id,
                        "name": run.name,
                        "workflow_id": run.workflow_id,
                        "workflow_public_id": run.workflow.public_id if run.workflow else None,
                        "workflow_name": run.workflow.name if run.workflow else None,
                        "user_id": run.workflow.user_id if run.workflow else None,
                        "organization_id": organization.id if organization else None,
                        "organization_name": organization.provider_id
                        if organization
                        else None,
                        "mode": run.mode,
                        "is_completed": run.is_completed,
                        "recording_url": run.recording_url,
                        "transcript_url": run.transcript_url,
                        "usage_info": run.usage_info,
                        "cost_info": run.cost_info,
                        "initial_context": run.initial_context,
                        "gathered_context": run.gathered_context,
                        "admin_comment": (run.annotations or {}).get("admin_comment"),
                        "admin_comment_ts": (run.annotations or {}).get(
                            "admin_comment_ts"
                        ),
                        "created_at": run.created_at,
                    }
                )

            return formatted_runs, total_count

    async def get_workflow_run(
        self, run_id: int, user_id: int = None, organization_id: int = None
    ) -> WorkflowRunModel | None:
        async with self.async_session() as session:
            query = select(WorkflowRunModel).join(WorkflowRunModel.workflow)

            if organization_id:
                # Filter by organization_id when provided
                query = query.where(
                    WorkflowRunModel.id == run_id,
                    WorkflowModel.organization_id == organization_id,
                )
            elif user_id:
                # Fallback to user_id for backwards compatibility
                query = query.where(
                    WorkflowRunModel.id == run_id,
                    WorkflowModel.user_id == user_id,
                )
            else:
                query = query.where(WorkflowRunModel.id == run_id)

            result = await session.execute(query)
            return result.scalars().first()

    async def get_workflow_run_by_id(self, run_id: int) -> WorkflowRunModel | None:
        """Get workflow run by ID without user filtering - for background tasks"""
        async with self.async_session() as session:
            result = await session.execute(
                select(WorkflowRunModel)
                .options(
                    joinedload(WorkflowRunModel.workflow).joinedload(WorkflowModel.user)
                )
                .where(WorkflowRunModel.id == run_id)
            )
            return result.scalars().first()

    async def get_workflow_runs_by_workflow_id(
        self,
        workflow_id: int,
        user_id: int = None,
        organization_id: int = None,
        limit: int = 50,
        offset: int = 0,
        filters: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[list[WorkflowRunResponseSchema], int]:
        async with self.async_session() as session:
            # Build base query
            base_query = (
                select(WorkflowRunModel)
                .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                .where(WorkflowRunModel.workflow_id == workflow_id)
            )

            if organization_id:
                # Filter by organization_id when provided
                base_query = base_query.where(
                    WorkflowModel.organization_id == organization_id
                )
            elif user_id:
                # Fallback to user_id for backwards compatibility
                base_query = base_query.where(WorkflowModel.user_id == user_id)

            # Apply filters
            base_query = apply_workflow_run_filters(base_query, filters)

            # Count total with filters
            count_query = base_query.with_only_columns(func.count(WorkflowRunModel.id))
            count_result = await session.execute(count_query)
            total_count = count_result.scalar()

            # Get paginated results with filters
            result = await session.execute(
                base_query.order_by(WorkflowRunModel.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            runs = [
                WorkflowRunResponseSchema.model_validate(
                    {
                        "id": run.id,
                        "workflow_id": run.workflow_id,
                        "name": run.name,
                        "mode": run.mode,
                        "created_at": run.created_at,
                        "is_completed": run.is_completed,
                        "recording_url": run.recording_url,
                        "transcript_url": run.transcript_url,
                        "cost_info": {
                            "dograh_token_usage": (
                                run.cost_info.get("dograh_token_usage")
                                if run.cost_info
                                and "dograh_token_usage" in run.cost_info
                                else round(
                                    float(run.cost_info.get("total_cost_usd", 0)) * 100,
                                    2,
                                )
                                if run.cost_info and "total_cost_usd" in run.cost_info
                                else 0
                            ),
                            "call_duration_seconds": int(
                                round(run.cost_info.get("call_duration_seconds") or 0)
                            )
                            if run.cost_info
                            else None,
                        }
                        if run.cost_info
                        else None,
                        "definition_id": run.definition_id,
                        "initial_context": run.initial_context,
                        "gathered_context": run.gathered_context,
                    }
                )
                for run in result.scalars().all()
            ]
            return runs, total_count

    async def update_workflow_run(
        self,
        run_id: int,
        is_completed: bool = False,
        recording_url: str | None = None,
        transcript_url: str | None = None,
        storage_backend: str | None = None,
        usage_info: dict | None = None,
        cost_info: dict | None = None,
        initial_context: dict | None = None,
        gathered_context: dict | None = None,
        logs: dict | None = None,
        state: str | None = None,
    ) -> WorkflowRunModel:
        async with self.async_session() as session:
            result = await session.execute(
                select(WorkflowRunModel).where(WorkflowRunModel.id == run_id)
            )
            run = result.scalars().first()
            if not run:
                raise ValueError(f"Workflow run with ID {run_id} not found")
            if recording_url:
                run.recording_url = recording_url
            if transcript_url:
                run.transcript_url = transcript_url
            if storage_backend:
                run.storage_backend = storage_backend
            if usage_info:
                run.usage_info = usage_info
                flag_modified(run, "usage_info")
            if cost_info:
                run.cost_info = cost_info
                flag_modified(run, "cost_info")
            if initial_context:
                run.initial_context = initial_context
                flag_modified(run, "initial_context")
            if gathered_context:
                run.gathered_context = {
                    **run.gathered_context,
                    **gathered_context,
                }
                flag_modified(run, "gathered_context")
            if logs:
                run.logs = {**run.logs, **logs}
                flag_modified(run, "logs")
            if is_completed:
                run.is_completed = is_completed
            if state:
                run.state = state
            try:
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise e
            await session.refresh(run)
        return run

    async def update_admin_comment(
        self, run_id: int, admin_comment: str
    ) -> WorkflowRunModel:
        """Update (or create) the admin comment inside the ``annotations`` JSON column.

        The comment is stored under the key ``admin_comment`` so we do not
        overwrite any other existing annotations that may be present.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(WorkflowRunModel).where(WorkflowRunModel.id == run_id)
            )
            run = result.scalars().first()
            if run is None:
                raise ValueError(f"Workflow run with ID {run_id} not found")

            # Ensure we never mutate a shared dict between instances
            current_annotations = dict(run.annotations or {})
            current_annotations["admin_comment"] = admin_comment

            current_annotations["admin_comment_ts"] = datetime.now(
                timezone.utc
            ).isoformat()
            run.annotations = current_annotations

            try:
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise e
            await session.refresh(run)
        return run

    async def get_runs_by_phone_number(
        self,
        phone_number: str,
        workflow_id: Optional[int] = None,
        organization_id: Optional[int] = None,
        limit: int = 5,
        exclude_run_id: Optional[int] = None,
    ) -> List[WorkflowRunModel]:
        """
        Look up recent completed calls for a given phone number.

        Used by the Caller Memory feature to greet returning callers in context.
        Searches three locations to handle outbound AND inbound + legacy data:
          - initial_context.phone_number  (canonical, outbound + inbound)
          - initial_context.phone          (legacy)
          - gathered_context.caller_number (inbound call identity)

        Results are scoped to a single workflow (so caller memory from one
        restaurant isn't leaked into another restaurant's agent) and optionally
        to an organization.

        Args:
            phone_number: The phone number to search for (exact match preferred;
                we use contains-match so +1 vs (country) formatting differences
                still resolve).
            workflow_id: Limit results to this workflow. Required in practice
                to avoid cross-tenant memory leaks.
            organization_id: Extra safety: only return runs in this org.
            limit: How many recent calls to return (default 5).
            exclude_run_id: If set, excludes this specific run (the current call).

        Returns:
            List of WorkflowRunModel ordered by created_at descending.
        """
        if not phone_number or not phone_number.strip():
            return []
        phone = phone_number.strip()

        async with self.async_session() as session:
            init_ctx = cast(WorkflowRunModel.initial_context, JSONB)
            gath_ctx = cast(WorkflowRunModel.gathered_context, JSONB)

            query = (
                select(WorkflowRunModel)
                .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                .where(
                    or_(
                        init_ctx["phone_number"].as_string().contains(phone),
                        init_ctx["phone"].as_string().contains(phone),
                        gath_ctx["caller_number"].as_string().contains(phone),
                    ),
                    WorkflowRunModel.is_completed == True,
                )
            )

            if workflow_id is not None:
                query = query.where(WorkflowRunModel.workflow_id == workflow_id)
            if organization_id is not None:
                query = query.where(WorkflowModel.organization_id == organization_id)
            if exclude_run_id is not None:
                query = query.where(WorkflowRunModel.id != exclude_run_id)

            query = query.order_by(WorkflowRunModel.created_at.desc()).limit(limit)

            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_workflow_run_with_context(
        self, workflow_run_id: int
    ) -> Tuple[Optional[WorkflowRunModel], Optional[int]]:
        """
        Get workflow run with all related data and return organization_id.

        Returns:
            Tuple of (workflow_run, organization_id) or (None, None) if not found
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(WorkflowRunModel)
                .options(
                    selectinload(WorkflowRunModel.workflow).selectinload(
                        WorkflowModel.user
                    )
                )
                .where(WorkflowRunModel.id == workflow_run_id)
            )
            workflow_run = result.scalars().first()

            if not workflow_run:
                return None, None

            if not workflow_run.workflow or not workflow_run.workflow.user:
                return workflow_run, None

            organization_id = workflow_run.workflow.user.selected_organization_id
            return workflow_run, organization_id
