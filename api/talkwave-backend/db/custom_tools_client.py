"""Database client for custom tools operations."""

from datetime import UTC, datetime
from typing import List, Optional, Tuple

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from api.db.database import async_session
from api.db.models import (
    CustomToolModel,
    ToolExecutionModel,
    WebhookEndpointModel,
)
from api.enums import ExecutionStatus, HttpMethod, ToolType


class CustomToolsClient:
    """Database client for custom tools operations."""

    # ==========================================================================
    # Custom Tools CRUD
    # ==========================================================================

    async def create_tool(
        self,
        organization_id: int,
        name: str,
        display_name: str,
        description: str,
        tool_type: ToolType,
        configuration: dict,
        input_schema: dict,
        output_schema: Optional[dict] = None,
        timeout_seconds: int = 30,
        retry_config: Optional[dict] = None,
        created_by: Optional[int] = None,
    ) -> CustomToolModel:
        """Create a new custom tool."""
        async with async_session() as session:
            tool = CustomToolModel(
                organization_id=organization_id,
                name=name,
                display_name=display_name,
                description=description,
                tool_type=tool_type,
                configuration=configuration,
                input_schema=input_schema,
                output_schema=output_schema,
                timeout_seconds=timeout_seconds,
                retry_config=retry_config,
                created_by=created_by,
            )
            session.add(tool)
            await session.commit()
            await session.refresh(tool)
            logger.info(f"Created custom tool: {tool.name} (id={tool.id})")
            return tool

    async def get_tool(
        self, tool_id: int, organization_id: Optional[int] = None
    ) -> Optional[CustomToolModel]:
        """Get a custom tool by ID."""
        async with async_session() as session:
            query = select(CustomToolModel).where(CustomToolModel.id == tool_id)
            if organization_id:
                query = query.where(CustomToolModel.organization_id == organization_id)
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def get_tool_by_name(
        self, name: str, organization_id: int
    ) -> Optional[CustomToolModel]:
        """Get a custom tool by name within an organization."""
        async with async_session() as session:
            query = select(CustomToolModel).where(
                CustomToolModel.name == name,
                CustomToolModel.organization_id == organization_id,
            )
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def get_all_tools(
        self,
        organization_id: int,
        tool_type: Optional[ToolType] = None,
        is_active: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[CustomToolModel], int]:
        """Get all custom tools for an organization with pagination."""
        async with async_session() as session:
            query = select(CustomToolModel).where(
                CustomToolModel.organization_id == organization_id
            )

            if tool_type:
                query = query.where(CustomToolModel.tool_type == tool_type)
            if is_active is not None:
                query = query.where(CustomToolModel.is_active == is_active)

            # Count total
            count_query = select(func.count()).select_from(query.subquery())
            total_count = await session.execute(count_query)
            total = total_count.scalar() or 0

            # Apply pagination and ordering
            query = query.order_by(CustomToolModel.created_at.desc())
            query = query.limit(limit).offset(offset)

            result = await session.execute(query)
            tools = list(result.scalars().all())

            return tools, total

    async def get_active_tools_for_workflow(
        self, organization_id: int
    ) -> List[CustomToolModel]:
        """Get all active custom tools that can be used in workflows."""
        async with async_session() as session:
            query = (
                select(CustomToolModel)
                .where(
                    CustomToolModel.organization_id == organization_id,
                    CustomToolModel.is_active == True,
                )
                .order_by(CustomToolModel.display_name)
            )
            result = await session.execute(query)
            return list(result.scalars().all())

    async def update_tool(
        self,
        tool_id: int,
        organization_id: int,
        **updates,
    ) -> Optional[CustomToolModel]:
        """Update a custom tool."""
        async with async_session() as session:
            query = select(CustomToolModel).where(
                CustomToolModel.id == tool_id,
                CustomToolModel.organization_id == organization_id,
            )
            result = await session.execute(query)
            tool = result.scalar_one_or_none()

            if not tool:
                return None

            # Don't allow updating system tools (except is_active)
            if tool.is_system and set(updates.keys()) - {"is_active"}:
                raise ValueError("Cannot modify system tools")

            for key, value in updates.items():
                if hasattr(tool, key):
                    setattr(tool, key, value)

            await session.commit()
            await session.refresh(tool)
            logger.info(f"Updated custom tool: {tool.name} (id={tool.id})")
            return tool

    async def delete_tool(self, tool_id: int, organization_id: int) -> bool:
        """Delete a custom tool."""
        async with async_session() as session:
            query = select(CustomToolModel).where(
                CustomToolModel.id == tool_id,
                CustomToolModel.organization_id == organization_id,
            )
            result = await session.execute(query)
            tool = result.scalar_one_or_none()

            if not tool:
                return False

            if tool.is_system:
                raise ValueError("Cannot delete system tools")

            await session.delete(tool)
            await session.commit()
            logger.info(f"Deleted custom tool: {tool.name} (id={tool_id})")
            return True

    # ==========================================================================
    # Tool Executions
    # ==========================================================================

    async def create_execution(
        self,
        tool_id: int,
        workflow_run_id: Optional[int] = None,
        input_data: Optional[dict] = None,
    ) -> ToolExecutionModel:
        """Create a new tool execution record."""
        async with async_session() as session:
            execution = ToolExecutionModel(
                tool_id=tool_id,
                workflow_run_id=workflow_run_id,
                status=ExecutionStatus.PENDING,
                input_data=input_data,
            )
            session.add(execution)
            await session.commit()
            await session.refresh(execution)
            return execution

    async def update_execution(
        self,
        execution_id: int,
        status: ExecutionStatus,
        output_data: Optional[dict] = None,
        error_message: Optional[str] = None,
        execution_time_ms: Optional[int] = None,
    ) -> Optional[ToolExecutionModel]:
        """Update a tool execution record."""
        async with async_session() as session:
            query = select(ToolExecutionModel).where(
                ToolExecutionModel.id == execution_id
            )
            result = await session.execute(query)
            execution = result.scalar_one_or_none()

            if not execution:
                return None

            execution.status = status
            if output_data is not None:
                execution.output_data = output_data
            if error_message is not None:
                execution.error_message = error_message
            if execution_time_ms is not None:
                execution.execution_time_ms = execution_time_ms
            if status in (ExecutionStatus.SUCCESS, ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT):
                execution.completed_at = datetime.now(UTC)

            await session.commit()
            await session.refresh(execution)
            return execution

    async def get_tool_executions(
        self,
        tool_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ToolExecutionModel]:
        """Get execution history for a tool."""
        async with async_session() as session:
            query = (
                select(ToolExecutionModel)
                .where(ToolExecutionModel.tool_id == tool_id)
                .order_by(ToolExecutionModel.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(query)
            return list(result.scalars().all())

    # ==========================================================================
    # Webhook Endpoints
    # ==========================================================================

    async def create_webhook_endpoint(
        self,
        organization_id: int,
        name: str,
        endpoint_url: str,
        http_method: HttpMethod = HttpMethod.POST,
        headers: Optional[dict] = None,
        auth_type: Optional[str] = None,
        auth_config: Optional[dict] = None,
    ) -> WebhookEndpointModel:
        """Create a new webhook endpoint."""
        async with async_session() as session:
            endpoint = WebhookEndpointModel(
                organization_id=organization_id,
                name=name,
                endpoint_url=endpoint_url,
                http_method=http_method,
                headers=headers,
                auth_type=auth_type,
                auth_config=auth_config,
            )
            session.add(endpoint)
            await session.commit()
            await session.refresh(endpoint)
            logger.info(f"Created webhook endpoint: {endpoint.name} (id={endpoint.id})")
            return endpoint

    async def get_webhook_endpoint(
        self, endpoint_id: int, organization_id: Optional[int] = None
    ) -> Optional[WebhookEndpointModel]:
        """Get a webhook endpoint by ID."""
        async with async_session() as session:
            query = select(WebhookEndpointModel).where(
                WebhookEndpointModel.id == endpoint_id
            )
            if organization_id:
                query = query.where(
                    WebhookEndpointModel.organization_id == organization_id
                )
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def get_all_webhook_endpoints(
        self, organization_id: int
    ) -> List[WebhookEndpointModel]:
        """Get all webhook endpoints for an organization."""
        async with async_session() as session:
            query = (
                select(WebhookEndpointModel)
                .where(WebhookEndpointModel.organization_id == organization_id)
                .order_by(WebhookEndpointModel.name)
            )
            result = await session.execute(query)
            return list(result.scalars().all())

    async def update_webhook_endpoint(
        self,
        endpoint_id: int,
        organization_id: int,
        **updates,
    ) -> Optional[WebhookEndpointModel]:
        """Update a webhook endpoint."""
        async with async_session() as session:
            query = select(WebhookEndpointModel).where(
                WebhookEndpointModel.id == endpoint_id,
                WebhookEndpointModel.organization_id == organization_id,
            )
            result = await session.execute(query)
            endpoint = result.scalar_one_or_none()

            if not endpoint:
                return None

            for key, value in updates.items():
                if hasattr(endpoint, key):
                    setattr(endpoint, key, value)

            await session.commit()
            await session.refresh(endpoint)
            return endpoint

    async def delete_webhook_endpoint(
        self, endpoint_id: int, organization_id: int
    ) -> bool:
        """Delete a webhook endpoint."""
        async with async_session() as session:
            query = select(WebhookEndpointModel).where(
                WebhookEndpointModel.id == endpoint_id,
                WebhookEndpointModel.organization_id == organization_id,
            )
            result = await session.execute(query)
            endpoint = result.scalar_one_or_none()

            if not endpoint:
                return False

            await session.delete(endpoint)
            await session.commit()
            logger.info(f"Deleted webhook endpoint: {endpoint.name} (id={endpoint_id})")
            return True


# Singleton instance
custom_tools_client = CustomToolsClient()





