"""
Tool Registry Service

Manages the registration and retrieval of custom tools for use in workflows.
Provides tool schemas for LLM function calling.
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from api.db.custom_tools_client import custom_tools_client
from api.db.models import CustomToolModel
from api.enums import ToolType


class ToolRegistry:
    """
    Registry for custom tools.
    
    Provides methods to:
    - Get tool definitions for LLM function calling
    - Validate tool configurations
    - Convert tools to pipecat-compatible format
    """

    def __init__(self):
        self._tool_cache: Dict[int, List[Dict[str, Any]]] = {}  # org_id -> tools

    async def get_tools_for_organization(
        self, organization_id: int, refresh: bool = False
    ) -> List[CustomToolModel]:
        """Get all active tools for an organization."""
        return await custom_tools_client.get_active_tools_for_workflow(organization_id)

    async def get_tool_schemas_for_llm(
        self, organization_id: int, tool_ids: Optional[List[int]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get tool schemas in LLM function calling format.
        
        Returns a list of tool definitions compatible with OpenAI/Anthropic function calling.
        """
        tools = await self.get_tools_for_organization(organization_id)
        
        if tool_ids:
            tools = [t for t in tools if t.id in tool_ids]
        
        schemas = []
        for tool in tools:
            schema = self._convert_to_function_schema(tool)
            if schema:
                schemas.append(schema)
        
        return schemas

    def _convert_to_function_schema(self, tool: CustomToolModel) -> Optional[Dict[str, Any]]:
        """
        Convert a CustomToolModel to an LLM function calling schema.
        
        The schema follows the OpenAI function calling format:
        {
            "type": "function",
            "function": {
                "name": "tool_name",
                "description": "Tool description",
                "parameters": {
                    "type": "object",
                    "properties": {...},
                    "required": [...]
                }
            }
        }
        """
        if not tool.is_active:
            return None

        try:
            # Build the parameters schema from the tool's input_schema
            parameters = tool.input_schema or {
                "type": "object",
                "properties": {},
                "required": [],
            }

            # Ensure required fields exist
            if "type" not in parameters:
                parameters["type"] = "object"
            if "properties" not in parameters:
                parameters["properties"] = {}
            if "required" not in parameters:
                parameters["required"] = []

            return {
                "type": "function",
                "function": {
                    "name": f"custom_{tool.name}",  # Prefix to avoid conflicts
                    "description": tool.description,
                    "parameters": parameters,
                },
                "tool_id": tool.id,  # Internal reference
                "tool_type": tool.tool_type.value,
            }
        except Exception as e:
            logger.error(f"Failed to convert tool {tool.name} to schema: {e}")
            return None

    def get_function_schema_simple(
        self,
        name: str,
        description: str,
        properties: Optional[Dict[str, Any]] = None,
        required: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a simple function schema for LLM function calling.
        
        Utility method for creating quick tool schemas.
        """
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties or {},
                    "required": required or [],
                },
            },
        }

    async def validate_tool_configuration(
        self, tool_type: ToolType, configuration: Dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """
        Validate a tool configuration based on its type.
        
        Returns:
            (is_valid, error_message)
        """
        validators = {
            ToolType.HTTP_REQUEST: self._validate_http_request_config,
            ToolType.WEBHOOK: self._validate_webhook_config,
            ToolType.DATABASE_QUERY: self._validate_database_query_config,
            ToolType.CUSTOM_CODE: self._validate_custom_code_config,
            ToolType.INTEGRATION: self._validate_integration_config,
        }

        validator = validators.get(tool_type)
        if not validator:
            return False, f"Unknown tool type: {tool_type}"

        return validator(configuration)

    def _validate_http_request_config(
        self, config: Dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """Validate HTTP request tool configuration."""
        required_fields = ["url", "method"]
        for field in required_fields:
            if field not in config:
                return False, f"Missing required field: {field}"

        valid_methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
        if config.get("method", "").upper() not in valid_methods:
            return False, f"Invalid HTTP method. Must be one of: {valid_methods}"

        url = config.get("url", "")
        if not url.startswith(("http://", "https://")):
            return False, "URL must start with http:// or https://"

        return True, None

    def _validate_webhook_config(
        self, config: Dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """Validate webhook tool configuration."""
        if "webhook_endpoint_id" not in config:
            return False, "Missing required field: webhook_endpoint_id"
        return True, None

    def _validate_database_query_config(
        self, config: Dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """Validate database query tool configuration."""
        if "webhook_endpoint_id" not in config:
            return False, "Missing required field: webhook_endpoint_id"
        
        valid_query_types = ["select", "insert", "update", "delete"]
        query_type = config.get("query_type", "").lower()
        if query_type and query_type not in valid_query_types:
            return False, f"Invalid query_type. Must be one of: {valid_query_types}"

        return True, None

    def _validate_custom_code_config(
        self, config: Dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """Validate custom code tool configuration."""
        if "runtime" not in config:
            return False, "Missing required field: runtime"
        if "code" not in config:
            return False, "Missing required field: code"

        valid_runtimes = ["javascript", "python"]
        if config.get("runtime", "").lower() not in valid_runtimes:
            return False, f"Invalid runtime. Must be one of: {valid_runtimes}"

        return True, None

    def _validate_integration_config(
        self, config: Dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """Validate integration tool configuration."""
        if "integration_id" not in config:
            return False, "Missing required field: integration_id"
        if "action" not in config:
            return False, "Missing required field: action"
        return True, None

    def clear_cache(self, organization_id: Optional[int] = None):
        """Clear the tool cache."""
        if organization_id:
            self._tool_cache.pop(organization_id, None)
        else:
            self._tool_cache.clear()


# Singleton instance
tool_registry = ToolRegistry()

