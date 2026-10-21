"""
Tool Executor Service

Handles the execution of custom tools during workflow runs.
Supports various tool types: HTTP requests, webhooks, database queries, custom code, and integrations.
"""

import asyncio
import json
import re
import time
from typing import Any, Dict, Optional

import httpx
from loguru import logger

from api.db.custom_tools_client import custom_tools_client
from api.db.models import CustomToolModel, WebhookEndpointModel
from api.enums import ExecutionStatus, ToolType


class ToolExecutor:
    """
    Executes custom tools and handles their results.
    
    Features:
    - Async execution with configurable timeouts
    - Retry logic for failed executions
    - Template variable substitution
    - Execution logging for debugging
    """

    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None

    async def get_http_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
            )
        return self._http_client

    async def execute_tool(
        self,
        tool: CustomToolModel,
        input_data: Dict[str, Any],
        workflow_run_id: Optional[int] = None,
        context_vars: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a custom tool and return the result.
        
        Args:
            tool: The custom tool to execute
            input_data: Input parameters from the LLM function call
            workflow_run_id: Optional workflow run ID for logging
            context_vars: Additional context variables for template substitution
        
        Returns:
            Dict containing the execution result or error
        """
        start_time = time.time()
        execution = None

        try:
            # Create execution record
            execution = await custom_tools_client.create_execution(
                tool_id=tool.id,
                workflow_run_id=workflow_run_id,
                input_data=input_data,
            )

            # Update status to running
            await custom_tools_client.update_execution(
                execution.id, status=ExecutionStatus.RUNNING
            )

            # Execute based on tool type
            result = await self._execute_by_type(
                tool, input_data, context_vars or {}
            )

            # Calculate execution time
            execution_time_ms = int((time.time() - start_time) * 1000)

            # Update execution record with success
            await custom_tools_client.update_execution(
                execution.id,
                status=ExecutionStatus.SUCCESS,
                output_data=result,
                execution_time_ms=execution_time_ms,
            )

            logger.info(
                f"Tool '{tool.name}' executed successfully in {execution_time_ms}ms"
            )
            return {"status": "success", "result": result}

        except asyncio.TimeoutError:
            execution_time_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Tool execution timed out after {tool.timeout_seconds}s"
            
            if execution:
                await custom_tools_client.update_execution(
                    execution.id,
                    status=ExecutionStatus.TIMEOUT,
                    error_message=error_msg,
                    execution_time_ms=execution_time_ms,
                )
            
            logger.error(f"Tool '{tool.name}' timed out: {error_msg}")
            return {"status": "error", "error": error_msg}

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)
            
            if execution:
                await custom_tools_client.update_execution(
                    execution.id,
                    status=ExecutionStatus.FAILED,
                    error_message=error_msg,
                    execution_time_ms=execution_time_ms,
                )
            
            logger.error(f"Tool '{tool.name}' failed: {error_msg}")
            return {"status": "error", "error": error_msg}

    async def _execute_by_type(
        self,
        tool: CustomToolModel,
        input_data: Dict[str, Any],
        context_vars: Dict[str, Any],
    ) -> Any:
        """Execute tool based on its type."""
        executors = {
            ToolType.HTTP_REQUEST: self._execute_http_request,
            ToolType.WEBHOOK: self._execute_webhook,
            ToolType.DATABASE_QUERY: self._execute_database_query,
            ToolType.CUSTOM_CODE: self._execute_custom_code,
            ToolType.INTEGRATION: self._execute_integration,
        }

        executor = executors.get(tool.tool_type)
        if not executor:
            raise ValueError(f"Unknown tool type: {tool.tool_type}")

        # Execute with timeout
        return await asyncio.wait_for(
            executor(tool, input_data, context_vars),
            timeout=tool.timeout_seconds,
        )

    async def _execute_http_request(
        self,
        tool: CustomToolModel,
        input_data: Dict[str, Any],
        context_vars: Dict[str, Any],
    ) -> Any:
        """Execute an HTTP request tool."""
        config = tool.configuration
        
        # Merge input_data with context_vars for template substitution
        template_vars = {**context_vars, **input_data}
        
        # Process URL with template variables
        url = self._render_template(config.get("url", ""), template_vars)
        method = config.get("method", "POST").upper()
        headers = config.get("headers", {})

        # SSRF guard: block private/loopback/metadata targets.
        from api.services.security.ssrf import assert_public_url

        await assert_public_url(url)
        
        # Process body template
        body_template = config.get("body_template", "")
        body = None
        if body_template:
            rendered_body = self._render_template(body_template, template_vars)
            try:
                body = json.loads(rendered_body)
            except json.JSONDecodeError:
                body = rendered_body

        # Add input_data as JSON body if no template and method is POST/PUT/PATCH
        if not body and method in ["POST", "PUT", "PATCH"]:
            body = input_data

        client = await self.get_http_client()
        
        # Make the request
        response = await client.request(
            method=method,
            url=url,
            headers=headers,
            json=body if isinstance(body, dict) else None,
            content=body if isinstance(body, str) else None,
        )

        response.raise_for_status()

        # Try to parse JSON response
        try:
            result = response.json()
        except json.JSONDecodeError:
            result = response.text

        # Extract specific path from response if configured
        response_path = config.get("response_path")
        if response_path and isinstance(result, dict):
            result = self._extract_json_path(result, response_path)

        return result

    async def _execute_webhook(
        self,
        tool: CustomToolModel,
        input_data: Dict[str, Any],
        context_vars: Dict[str, Any],
    ) -> Any:
        """Execute a webhook tool."""
        config = tool.configuration
        webhook_endpoint_id = config.get("webhook_endpoint_id")
        
        if not webhook_endpoint_id:
            raise ValueError("Webhook endpoint ID not configured")

        # Get webhook endpoint scoped to the tool's organization to prevent
        # cross-tenant webhook invocation via a guessed endpoint id.
        endpoint = await custom_tools_client.get_webhook_endpoint(
            webhook_endpoint_id, organization_id=tool.organization_id
        )
        if not endpoint:
            raise ValueError(f"Webhook endpoint {webhook_endpoint_id} not found")

        # Merge input_data with context_vars for template substitution
        template_vars = {**context_vars, **input_data}
        
        # Process payload template
        payload_template = config.get("payload_template", "")
        if payload_template:
            rendered_payload = self._render_template(payload_template, template_vars)
            try:
                payload = json.loads(rendered_payload)
            except json.JSONDecodeError:
                payload = {"data": rendered_payload}
        else:
            payload = input_data

        # Build headers
        headers = dict(endpoint.headers or {})
        headers = self._apply_auth(headers, endpoint)

        client = await self.get_http_client()
        
        # Make the webhook request
        response = await client.request(
            method=endpoint.http_method.value,
            url=endpoint.endpoint_url,
            headers=headers,
            json=payload,
        )

        response.raise_for_status()

        try:
            return response.json()
        except json.JSONDecodeError:
            return {"response": response.text, "status_code": response.status_code}

    async def _execute_database_query(
        self,
        tool: CustomToolModel,
        input_data: Dict[str, Any],
        context_vars: Dict[str, Any],
    ) -> Any:
        """
        Execute a database query tool via webhook.
        
        Database queries are executed through a secure webhook endpoint
        that handles the actual database operations.
        """
        config = tool.configuration
        webhook_endpoint_id = config.get("webhook_endpoint_id")
        
        if not webhook_endpoint_id:
            raise ValueError("Database webhook endpoint ID not configured")

        # Get webhook endpoint scoped to the tool's organization.
        endpoint = await custom_tools_client.get_webhook_endpoint(
            webhook_endpoint_id, organization_id=tool.organization_id
        )
        if not endpoint:
            raise ValueError(f"Database webhook endpoint {webhook_endpoint_id} not found")

        # Build the database request payload
        payload = {
            "query_type": config.get("query_type", "select"),
            "table_hint": config.get("table_hint"),
            "parameters": input_data,
            "context": context_vars,
        }

        # Build headers with auth
        headers = dict(endpoint.headers or {})
        headers = self._apply_auth(headers, endpoint)

        client = await self.get_http_client()
        
        response = await client.request(
            method=endpoint.http_method.value,
            url=endpoint.endpoint_url,
            headers=headers,
            json=payload,
        )

        response.raise_for_status()
        return response.json()

    async def _execute_custom_code(
        self,
        tool: CustomToolModel,
        input_data: Dict[str, Any],
        context_vars: Dict[str, Any],
    ) -> Any:
        """
        Execute custom code in a sandboxed environment.
        
        For security, custom code is executed via a webhook to a sandboxed
        code execution service (like AWS Lambda, Cloudflare Workers, etc.)
        """
        config = tool.configuration
        runtime = config.get("runtime", "javascript")
        code = config.get("code", "")
        
        # If there's a sandbox webhook configured, use it
        sandbox_config = config.get("sandbox_config", {})
        webhook_url = sandbox_config.get("webhook_url")
        
        if webhook_url:
            from api.services.security.ssrf import assert_public_url

            await assert_public_url(webhook_url)
            client = await self.get_http_client()
            response = await client.post(
                webhook_url,
                json={
                    "runtime": runtime,
                    "code": code,
                    "input": input_data,
                    "context": context_vars,
                },
            )
            response.raise_for_status()
            return response.json()
        
        # Local execution (basic, limited functionality)
        if runtime == "javascript":
            return await self._execute_javascript_local(code, input_data, context_vars)
        elif runtime == "python":
            return await self._execute_python_local(code, input_data, context_vars)
        else:
            raise ValueError(f"Unsupported runtime: {runtime}")

    async def _execute_javascript_local(
        self, code: str, input_data: Dict[str, Any], context_vars: Dict[str, Any]
    ) -> Any:
        """
        Execute JavaScript code locally (limited, for simple transformations).
        
        Note: For production use, this should be executed in a proper sandbox.
        """
        # This is a placeholder - in production, use a proper JS sandbox
        # like quickjs or a webhook to a Node.js function
        logger.warning("Local JavaScript execution is limited. Consider using a sandbox webhook.")
        
        # Simple expression evaluation for basic cases
        if "return" not in code and "function" not in code:
            # Assume it's a simple expression
            try:
                # Very basic - just return input with some processing
                merged = {**context_vars, **input_data}
                return {"processed": True, "input": merged}
            except Exception as e:
                return {"error": str(e)}
        
        return {"warning": "Complex JavaScript requires sandbox webhook", "input": input_data}

    async def _execute_python_local(
        self, code: str, input_data: Dict[str, Any], context_vars: Dict[str, Any]
    ) -> Any:
        """Local Python execution is disabled for security.

        The previous implementation used ``exec()`` with a restricted
        ``__builtins__`` dict, which is trivially escapable (e.g. via
        ``().__class__.__bases__``) and amounts to arbitrary code execution in
        the API process. Custom Python code MUST run in an isolated sandbox
        reached via a ``sandbox_config.webhook_url``; there is no in-process
        interpreter fallback.
        """
        raise ValueError(
            "In-process Python execution is disabled. Configure a sandboxed "
            "code-execution service via sandbox_config.webhook_url."
        )

    async def _execute_integration(
        self,
        tool: CustomToolModel,
        input_data: Dict[str, Any],
        context_vars: Dict[str, Any],
    ) -> Any:
        """Execute an integration tool (e.g., CRM, calendar, etc.)."""
        config = tool.configuration
        integration_id = config.get("integration_id")
        action = config.get("action")
        mapping = config.get("mapping", {})
        
        # This would integrate with Nango or other integration services
        # For now, return a placeholder
        logger.info(f"Integration execution: {integration_id}.{action}")
        
        return {
            "status": "integration_called",
            "integration": integration_id,
            "action": action,
            "input": input_data,
        }

    def _render_template(self, template: str, variables: Dict[str, Any]) -> str:
        """
        Render a template string with variable substitution.
        
        Supports {{variable}} syntax for simple substitution.
        """
        if not template:
            return template

        def replace_var(match):
            var_name = match.group(1).strip()
            value = variables.get(var_name, match.group(0))
            if isinstance(value, (dict, list)):
                return json.dumps(value)
            return str(value)

        pattern = r"\{\{(\s*[\w.]+\s*)\}\}"
        return re.sub(pattern, replace_var, template)

    def _extract_json_path(self, data: Dict[str, Any], path: str) -> Any:
        """
        Extract a value from a dict using a simple JSONPath-like syntax.
        
        Supports: $.key.subkey or key.subkey
        """
        if path.startswith("$."):
            path = path[2:]
        
        parts = path.split(".")
        current = data
        
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit():
                current = current[int(part)]
            else:
                return None
        
        return current

    def _apply_auth(
        self, headers: Dict[str, str], endpoint: WebhookEndpointModel
    ) -> Dict[str, str]:
        """Apply authentication to headers based on endpoint config."""
        if not endpoint.auth_type or endpoint.auth_type == "none":
            return headers

        auth_config = endpoint.auth_config or {}

        if endpoint.auth_type == "api_key":
            header_name = auth_config.get("header_name", "X-API-Key")
            headers[header_name] = auth_config.get("api_key", "")
        
        elif endpoint.auth_type == "bearer":
            headers["Authorization"] = f"Bearer {auth_config.get('token', '')}"
        
        elif endpoint.auth_type == "basic":
            import base64
            credentials = f"{auth_config.get('username', '')}:{auth_config.get('password', '')}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        
        # OAuth2 would require token refresh logic, handled separately

        return headers

    async def test_tool(
        self,
        tool: CustomToolModel,
        test_input: Dict[str, Any],
        context_vars: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Test a tool with sample input.
        
        Similar to execute_tool but doesn't create execution records
        and includes more detailed output for debugging.
        """
        start_time = time.time()
        
        try:
            result = await self._execute_by_type(
                tool, test_input, context_vars or {}
            )
            execution_time_ms = int((time.time() - start_time) * 1000)
            
            return {
                "status": "success",
                "result": result,
                "execution_time_ms": execution_time_ms,
            }
        except asyncio.TimeoutError:
            return {
                "status": "timeout",
                "error": f"Execution timed out after {tool.timeout_seconds}s",
                "execution_time_ms": int((time.time() - start_time) * 1000),
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__,
                "execution_time_ms": int((time.time() - start_time) * 1000),
            }

    async def close(self):
        """Close the HTTP client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()


# Singleton instance
tool_executor = ToolExecutor()

