"""
Action Executors for Action Node.
Handles execution of various action types: SMS, Email, Webhook, API calls, etc.
"""

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

import aiohttp
from loguru import logger

from api.services.workflow.dto import ActionConfigDTO, ActionTypeEnum


class ActionExecutionResult:
    """Result of an action execution."""

    def __init__(
        self,
        action_id: str,
        action_type: str,
        success: bool,
        message: str = "",
        response_data: Optional[Dict[str, Any]] = None,
    ):
        self.action_id = action_id
        self.action_type = action_type
        self.success = success
        self.message = message
        self.response_data = response_data or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "success": self.success,
            "message": self.message,
            "response_data": self.response_data,
        }


def substitute_variables(template: str, variables: Dict[str, Any]) -> str:
    """
    Substitute variables in template string.
    Supports {{variable_name}} syntax.
    """
    if not template:
        return template

    def replace_var(match):
        var_name = match.group(1).strip()
        value = variables.get(var_name, match.group(0))
        if value is None:
            return ""
        return str(value)

    return re.sub(r"\{\{(\s*\w+\s*)\}\}", replace_var, template)


class TwilioSmsExecutor:
    """Execute SMS sending via Twilio."""

    def __init__(
        self, 
        account_sid: str, 
        auth_token: str, 
        from_number: str = None,
        messaging_service_sid: str = None
    ):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.messaging_service_sid = messaging_service_sid.strip() if messaging_service_sid else None
        
        # Normalize from_number to E.164 format
        from_number = from_number.strip() if from_number else ""
        if from_number and not from_number.startswith('+'):
            from_number = f"+{from_number}"
        self.from_number = from_number if from_number else None

    async def send_sms(
        self, to_number: str, message: str, variables: Dict[str, Any] = None
    ) -> ActionExecutionResult:
        """Send SMS via Twilio."""
        if variables:
            to_number = substitute_variables(to_number, variables)
            message = substitute_variables(message, variables)

        # Normalize phone number to E.164 format (must start with +)
        to_number = to_number.strip()
        
        # Remove non-digit characters except + at the start
        if to_number.startswith('+'):
            to_number = "+" + "".join(c for c in to_number[1:] if c.isdigit())
        else:
            to_number = "".join(c for c in to_number if c.isdigit())
            to_number = f"+{to_number}" if to_number else ""
        
        logger.info(f"Sending SMS to normalized number: {to_number}")

        endpoint = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"

        # Build request data - use MessagingServiceSid if available, otherwise use From number
        data = {
            "To": to_number,
            "Body": message,
        }
        
        if self.messaging_service_sid:
            # Use Messaging Service SID (preferred for A2P 10DLC, toll-free, etc.)
            data["MessagingServiceSid"] = self.messaging_service_sid
            logger.info(f"Using Messaging Service SID: {self.messaging_service_sid[:10]}...")
        elif self.from_number:
            # Use direct From number
            data["From"] = self.from_number
            logger.info(f"Using From number: {self.from_number}")
        else:
            return ActionExecutionResult(
                action_id="sms",
                action_type="send_sms",
                success=False,
                message="No From number or Messaging Service SID configured",
            )

        try:
            async with aiohttp.ClientSession() as session:
                auth = aiohttp.BasicAuth(self.account_sid, self.auth_token)
                async with session.post(endpoint, data=data, auth=auth) as response:
                    response_data = await response.json()
                    
                    # Log full response for debugging
                    logger.info(f"Twilio API response status: {response.status}")
                    logger.info(f"Twilio API response: {response_data}")

                    if response.status in (200, 201):
                        # Check if message was actually queued/sent
                        status = response_data.get('status', 'unknown')
                        sid = response_data.get('sid', 'N/A')
                        logger.info(f"SMS sent successfully to {to_number} - SID: {sid}, Status: {status}")
                        return ActionExecutionResult(
                            action_id="sms",
                            action_type="send_sms",
                            success=True,
                            message=f"SMS sent to {to_number} (SID: {sid}, Status: {status})",
                            response_data=response_data,
                        )
                    else:
                        error_code = response_data.get('code', 'N/A')
                        error_msg = response_data.get('message', 'Unknown error')
                        logger.error(f"Failed to send SMS: Code={error_code}, Message={error_msg}")
                        return ActionExecutionResult(
                            action_id="sms",
                            action_type="send_sms",
                            success=False,
                            message=f"Failed to send SMS: {error_msg} (Code: {error_code})",
                            response_data=response_data,
                        )
        except Exception as e:
            logger.error(f"Error sending SMS: {e}")
            return ActionExecutionResult(
                action_id="sms",
                action_type="send_sms",
                success=False,
                message=f"Error sending SMS: {str(e)}",
            )


class TwilioWhatsAppExecutor:
    """Execute WhatsApp message sending via Twilio."""

    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        self.account_sid = account_sid
        self.auth_token = auth_token
        # WhatsApp numbers must be prefixed with "whatsapp:"
        # Normalize the from_number - strip and add prefix if needed
        from_number = (from_number or "").strip()
        if from_number and not from_number.startswith("whatsapp:"):
            # Also normalize phone format - add + if missing
            if from_number and not from_number.startswith("+"):
                from_number = f"+{from_number}"
            from_number = f"whatsapp:{from_number}"
        self.from_number = from_number
        logger.info(f"TwilioWhatsAppExecutor initialized with from_number: {self.from_number}")

    async def send_message(
        self, to_number: str, message: str, variables: Dict[str, Any] = None
    ) -> ActionExecutionResult:
        """Send WhatsApp message via Twilio."""
        if variables:
            to_number = substitute_variables(to_number, variables)
            message = substitute_variables(message, variables)

        # Normalize to_number - strip and clean phone number
        to_number = (to_number or "").strip()
        
        # Remove any existing whatsapp: prefix to normalize
        if to_number.startswith("whatsapp:"):
            to_number = to_number[9:]  # Remove "whatsapp:" prefix
        
        # Remove non-digit characters except + at the start
        if to_number.startswith("+"):
            to_number = "+" + "".join(c for c in to_number[1:] if c.isdigit())
        else:
            to_number = "".join(c for c in to_number if c.isdigit())
            to_number = f"+{to_number}" if to_number else ""
        
        # Add whatsapp: prefix
        if to_number:
            to_number = f"whatsapp:{to_number}"

        endpoint = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"

        data = {
            "To": to_number,
            "From": self.from_number,
            "Body": message,
        }

        logger.info(f"Sending WhatsApp message: From={self.from_number}, To={to_number}")

        try:
            async with aiohttp.ClientSession() as session:
                auth = aiohttp.BasicAuth(self.account_sid, self.auth_token)
                async with session.post(endpoint, data=data, auth=auth) as response:
                    response_data = await response.json()

                    if response.status in (200, 201):
                        logger.info(f"WhatsApp message sent successfully to {to_number} - SID: {response_data.get('sid')}")
                        return ActionExecutionResult(
                            action_id="whatsapp",
                            action_type="send_whatsapp",
                            success=True,
                            message=f"WhatsApp message sent to {to_number}",
                            response_data=response_data,
                        )
                    else:
                        error_code = response_data.get('code', 'Unknown')
                        error_msg = response_data.get('message', 'Unknown error')
                        
                        # Provide helpful error messages for common issues
                        if error_code == 63007:
                            error_msg = (
                                f"WhatsApp sender not configured. "
                                f"The 'From' number ({self.from_number}) is not a valid WhatsApp sender. "
                                f"For testing, use Twilio Sandbox number: whatsapp:+14155238886. "
                                f"Recipients must first send 'join <sandbox-code>' to join your sandbox."
                            )
                        elif error_code == 63016:
                            error_msg = (
                                f"Recipient has not opted-in to receive messages. "
                                f"For Twilio Sandbox, the recipient must first send 'join <sandbox-code>' "
                                f"to +14155238886 on WhatsApp."
                            )
                        
                        logger.error(f"Failed to send WhatsApp message: {error_msg} (code: {error_code})")
                        return ActionExecutionResult(
                            action_id="whatsapp",
                            action_type="send_whatsapp",
                            success=False,
                            message=f"Failed to send WhatsApp: {error_msg}",
                            response_data=response_data,
                        )
        except Exception as e:
            logger.error(f"Error sending WhatsApp message: {e}")
            return ActionExecutionResult(
                action_id="whatsapp",
                action_type="send_whatsapp",
                success=False,
                message=f"Error sending WhatsApp: {str(e)}",
            )


class SlackExecutor:
    """Execute Slack message sending."""

    def __init__(self, bot_token: str, default_channel: str = None):
        self.bot_token = bot_token
        self.default_channel = default_channel

    async def send_message(
        self, channel: str = None, message: str = "", variables: Dict[str, Any] = None
    ) -> ActionExecutionResult:
        """Send message to Slack channel."""
        if variables:
            if channel:
                channel = substitute_variables(channel, variables)
            message = substitute_variables(message, variables)

        target_channel = channel or self.default_channel
        if not target_channel:
            return ActionExecutionResult(
                action_id="slack",
                action_type="send_slack",
                success=False,
                message="No Slack channel specified",
            )

        endpoint = "https://slack.com/api/chat.postMessage"

        headers = {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json",
        }

        payload = {
            "channel": target_channel,
            "text": message,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(endpoint, json=payload, headers=headers) as response:
                    response_data = await response.json()

                    if response_data.get("ok"):
                        logger.info(f"Slack message sent successfully to {target_channel}")
                        return ActionExecutionResult(
                            action_id="slack",
                            action_type="send_slack",
                            success=True,
                            message=f"Message sent to {target_channel}",
                            response_data=response_data,
                        )
                    else:
                        error = response_data.get("error", "Unknown error")
                        logger.error(f"Failed to send Slack message: {error}")
                        return ActionExecutionResult(
                            action_id="slack",
                            action_type="send_slack",
                            success=False,
                            message=f"Failed to send Slack message: {error}",
                            response_data=response_data,
                        )
        except Exception as e:
            logger.error(f"Error sending Slack message: {e}")
            return ActionExecutionResult(
                action_id="slack",
                action_type="send_slack",
                success=False,
                message=f"Error sending Slack message: {str(e)}",
            )


class SmtpEmailExecutor:
    """Execute email sending via SMTP."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_email: str,
        use_tls: bool = True,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.use_tls = use_tls

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        is_html: bool = False,
        variables: Dict[str, Any] = None,
    ) -> ActionExecutionResult:
        """Send email via SMTP."""
        import aiosmtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        if variables:
            to_email = substitute_variables(to_email, variables)
            subject = substitute_variables(subject, variables)
            body = substitute_variables(body, variables)

        try:
            message = MIMEMultipart("alternative")
            message["From"] = self.from_email
            message["To"] = to_email
            message["Subject"] = subject

            content_type = "html" if is_html else "plain"
            message.attach(MIMEText(body, content_type))

            await aiosmtplib.send(
                message,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.username,
                password=self.password,
                start_tls=self.use_tls,
            )

            logger.info(f"Email sent successfully to {to_email}")
            return ActionExecutionResult(
                action_id="email",
                action_type="send_email",
                success=True,
                message=f"Email sent to {to_email}",
            )
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return ActionExecutionResult(
                action_id="email",
                action_type="send_email",
                success=False,
                message=f"Error sending email: {str(e)}",
            )


class SendGridEmailExecutor:
    """Execute email sending via SendGrid API."""

    def __init__(self, api_key: str, from_email: str):
        self.api_key = api_key
        self.from_email = from_email

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        is_html: bool = False,
        variables: Dict[str, Any] = None,
    ) -> ActionExecutionResult:
        """Send email via SendGrid."""
        if variables:
            to_email = substitute_variables(to_email, variables)
            subject = substitute_variables(subject, variables)
            body = substitute_variables(body, variables)

        endpoint = "https://api.sendgrid.com/v3/mail/send"

        content_type = "text/html" if is_html else "text/plain"
        payload = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": self.from_email},
            "subject": subject,
            "content": [{"type": content_type, "value": body}],
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    endpoint, json=payload, headers=headers
                ) as response:
                    if response.status in (200, 202):
                        logger.info(f"Email sent successfully to {to_email} via SendGrid")
                        return ActionExecutionResult(
                            action_id="email",
                            action_type="send_email",
                            success=True,
                            message=f"Email sent to {to_email}",
                        )
                    else:
                        response_text = await response.text()
                        logger.error(f"Failed to send email via SendGrid: {response_text}")
                        return ActionExecutionResult(
                            action_id="email",
                            action_type="send_email",
                            success=False,
                            message=f"Failed to send email: {response_text}",
                        )
        except Exception as e:
            logger.error(f"Error sending email via SendGrid: {e}")
            return ActionExecutionResult(
                action_id="email",
                action_type="send_email",
                success=False,
                message=f"Error sending email: {str(e)}",
            )


class MailgunEmailExecutor:
    """Execute email sending via Mailgun API."""

    def __init__(self, api_key: str, domain: str, from_email: str, region: str = "us"):
        self.api_key = api_key
        self.domain = domain
        self.from_email = from_email
        # Mailgun has US and EU regions with different base URLs
        self.base_url = "https://api.eu.mailgun.net" if region == "eu" else "https://api.mailgun.net"

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        is_html: bool = False,
        variables: Dict[str, Any] = None,
    ) -> ActionExecutionResult:
        """Send email via Mailgun."""
        if variables:
            to_email = substitute_variables(to_email, variables)
            subject = substitute_variables(subject, variables)
            body = substitute_variables(body, variables)

        endpoint = f"{self.base_url}/v3/{self.domain}/messages"

        data = {
            "from": self.from_email,
            "to": to_email,
            "subject": subject,
        }
        
        if is_html:
            data["html"] = body
        else:
            data["text"] = body

        try:
            async with aiohttp.ClientSession() as session:
                auth = aiohttp.BasicAuth("api", self.api_key)
                async with session.post(endpoint, data=data, auth=auth) as response:
                    response_data = await response.json()

                    if response.status == 200:
                        logger.info(f"Email sent successfully to {to_email} via Mailgun")
                        return ActionExecutionResult(
                            action_id="email",
                            action_type="send_email",
                            success=True,
                            message=f"Email sent to {to_email}",
                            response_data=response_data,
                        )
                    else:
                        logger.error(f"Failed to send email via Mailgun: {response_data}")
                        return ActionExecutionResult(
                            action_id="email",
                            action_type="send_email",
                            success=False,
                            message=f"Failed to send email: {response_data.get('message', 'Unknown error')}",
                            response_data=response_data,
                        )
        except Exception as e:
            logger.error(f"Error sending email via Mailgun: {e}")
            return ActionExecutionResult(
                action_id="email",
                action_type="send_email",
                success=False,
                message=f"Error sending email: {str(e)}",
            )


class WebhookExecutor:
    """Execute webhook/API calls."""

    async def execute(
        self,
        url: str,
        method: str = "POST",
        headers: Optional[Dict[str, str]] = None,
        body_template: Optional[str] = None,
        timeout_seconds: int = 30,
        variables: Dict[str, Any] = None,
    ) -> ActionExecutionResult:
        """Execute webhook/API call."""
        if variables:
            url = substitute_variables(url, variables)
            if body_template:
                body_template = substitute_variables(body_template, variables)
            if headers:
                headers = {
                    k: substitute_variables(v, variables) for k, v in headers.items()
                }

        if not url or not url.strip():
            return ActionExecutionResult(
                action_id="webhook",
                action_type="webhook",
                success=True,
                message="Webhook skipped (no URL configured)",
            )

        if not url.startswith(("http://", "https://")):
            return ActionExecutionResult(
                action_id="webhook",
                action_type="webhook",
                success=False,
                message=f"Invalid webhook URL: {url}. URL must start with http:// or https://",
            )

        # SSRF guard: block requests to private/loopback/metadata targets.
        from api.services.security.ssrf import validate_public_url

        if not await validate_public_url(url):
            return ActionExecutionResult(
                action_id="webhook",
                action_type="webhook",
                success=False,
                message="Webhook URL target is not permitted.",
            )

        try:
            body = None
            if body_template:
                try:
                    body = json.loads(body_template)
                except json.JSONDecodeError:
                    body = body_template

            timeout = aiohttp.ClientTimeout(total=timeout_seconds)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                request_kwargs = {
                    "url": url,
                    "headers": headers or {},
                }

                if method.upper() in ("POST", "PUT", "PATCH"):
                    if isinstance(body, dict):
                        request_kwargs["json"] = body
                    else:
                        request_kwargs["data"] = body

                async with session.request(method.upper(), **request_kwargs) as response:
                    response_text = await response.text()
                    try:
                        response_data = json.loads(response_text)
                    except json.JSONDecodeError:
                        response_data = {"raw": response_text}

                    if response.status < 400:
                        logger.info(f"Webhook executed successfully: {url}")
                        return ActionExecutionResult(
                            action_id="webhook",
                            action_type="webhook",
                            success=True,
                            message=f"Webhook executed: {url}",
                            response_data=response_data,
                        )
                    else:
                        logger.error(f"Webhook failed: {response_text}")
                        return ActionExecutionResult(
                            action_id="webhook",
                            action_type="webhook",
                            success=False,
                            message=f"Webhook failed with status {response.status}",
                            response_data=response_data,
                        )
        except asyncio.TimeoutError:
            logger.error(f"Webhook timeout: {url}")
            return ActionExecutionResult(
                action_id="webhook",
                action_type="webhook",
                success=False,
                message=f"Webhook timeout after {timeout_seconds}s",
            )
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return ActionExecutionResult(
                action_id="webhook",
                action_type="webhook",
                success=False,
                message=f"Webhook error: {str(e)}",
            )


class DatabaseQueryExecutor:
    """Execute database queries against configured databases (Supabase, PostgreSQL, etc.)."""

    @staticmethod
    def _flatten_dict_candidates(value: Any) -> List[Dict[str, Any]]:
        """Return nested dict candidates for credential extraction."""
        if not isinstance(value, dict):
            return []

        candidates: List[Dict[str, Any]] = []
        queue: List[Dict[str, Any]] = [value]
        seen_ids = set()

        while queue:
            current = queue.pop(0)
            current_id = id(current)
            if current_id in seen_ids:
                continue
            seen_ids.add(current_id)
            candidates.append(current)

            for nested_key in ("credentials", "config", "value"):
                nested = current.get(nested_key)
                if isinstance(nested, dict):
                    queue.append(nested)

        return candidates

    @classmethod
    def _extract_supabase_credentials(cls, raw_value: Any) -> Dict[str, str]:
        """Normalize Supabase credentials across integration storage formats."""
        best_project_url = ""
        best_api_key = ""

        for candidate in cls._flatten_dict_candidates(raw_value):
            project_url = str(
                candidate.get("project_url")
                or candidate.get("supabase_url")
                or candidate.get("url")
                or ""
            ).strip()

            # If no explicit URL, construct from project_id
            if not project_url:
                project_id = str(candidate.get("project_id") or "").strip()
                if project_id:
                    project_id = project_id.replace("https://", "").replace("http://", "").replace(".supabase.co", "").strip("/")
                    project_url = f"https://{project_id}.supabase.co"

            api_key = str(
                candidate.get("service_role_key")
                or candidate.get("api_key")
                or candidate.get("anon_key")
                or candidate.get("key")
                or candidate.get("token")
                or ""
            ).strip()

            if project_url and api_key:
                return {
                    "project_url": project_url.rstrip("/"),
                    "api_key": api_key,
                }

            if project_url and not best_project_url:
                best_project_url = project_url.rstrip("/")
            if api_key and not best_api_key:
                best_api_key = api_key

        return {"project_url": best_project_url, "api_key": best_api_key}

    @staticmethod
    def _parse_insert_body(query_template: str) -> Dict[str, Any]:
        """Convert whatever the user gives us into a JSON body for Supabase REST insert.

        Strategy: be as forgiving as possible. Accept JSON, SQL INSERT, or
        anything else — just get column→value pairs out and save the raw data.
        Numbers stay numbers, everything else is kept as-is (string).
        """
        if not query_template:
            return {}

        query_template = query_template.strip().rstrip(";").strip()

        # 1) Try JSON — if user already gave us a dict, use it directly
        try:
            parsed = json.loads(query_template)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        # 2) Try to extract columns + values from SQL INSERT
        #    INSERT INTO table (col1, col2) VALUES (val1, val2)
        upper = query_template.upper()
        if "VALUES" in upper:
            try:
                # Split at VALUES keyword
                values_pos = upper.index("VALUES")
                before_values = query_template[:values_pos]
                after_values = query_template[values_pos + 6:]  # len("VALUES") == 6

                # Columns: everything between the FIRST pair of parens before VALUES
                col_open = before_values.index("(")
                col_close = before_values.index(")", col_open)
                columns = [
                    c.strip().strip('"').strip("'").strip("`")
                    for c in before_values[col_open + 1 : col_close].split(",")
                ]

                # Values: everything between the FIRST '(' and LAST ')' after VALUES
                val_open = after_values.index("(")
                val_close = after_values.rfind(")")
                if val_close <= val_open:
                    val_close = len(after_values)
                raw_vals_str = after_values[val_open + 1 : val_close]

                # Split by comma, respecting single/double quotes
                vals: list = []
                buf = ""
                quote_char: str | None = None
                for ch in raw_vals_str:
                    if ch in ("'", '"') and quote_char is None:
                        quote_char = ch
                    elif ch == quote_char:
                        quote_char = None
                    elif ch == "," and quote_char is None:
                        vals.append(buf.strip())
                        buf = ""
                        continue
                    buf += ch
                vals.append(buf.strip())

                # Pad if needed
                while len(vals) < len(columns):
                    vals.append("")

                def _to_value(v: str) -> Any:
                    v = v.strip()
                    if not v or v.lower() in ("null", "none"):
                        return None
                    # Strip quotes
                    if len(v) >= 2 and v[0] in ("'", '"') and v[-1] == v[0]:
                        return v[1:-1]
                    # Keep numbers as numbers
                    try:
                        return int(v)
                    except ValueError:
                        pass
                    try:
                        return float(v)
                    except ValueError:
                        pass
                    # Everything else → raw string as-is
                    return v

                body: Dict[str, Any] = {}
                for col, raw in zip(columns, vals):
                    body[col] = _to_value(raw)

                if body:
                    return body
            except Exception as e:
                logger.debug(f"[SUPABASE] SQL parse attempt failed ({e}), using raw fallback")

        # 3) Fallback: save the entire query as raw text in a "data" column.
        #    This ensures we never lose data — Supabase will reject unknown
        #    columns, but at least the user sees what happened.
        return {"data": query_template}

    async def execute(
        self,
        database_service: str,
        operation: str,
        query_template: str,
        table_name: str = "",
        variables: Dict[str, Any] = None,
        organization_id: Optional[int] = None,
    ) -> ActionExecutionResult:
        """Execute a database query using stored credentials."""
        if variables:
            query_template = substitute_variables(query_template, variables)
            table_name = substitute_variables(table_name, variables)

        try:
            if database_service == "supabase":
                return await self._execute_supabase(operation, query_template, table_name, organization_id)
            elif database_service in ("postgresql", "mysql"):
                return await self._execute_sql_via_webhook(database_service, query_template, table_name, organization_id)
            else:
                return await self._execute_generic(database_service, operation, query_template, table_name)
        except Exception as e:
            logger.error(f"Database query error ({database_service}): {e}")
            return ActionExecutionResult(
                action_id="database_query", action_type="database_query",
                success=False, message=f"Database query failed: {str(e)}",
            )

    async def _execute_supabase(
        self, operation: str, query_template: str, table_name: str,
        organization_id: Optional[int] = None,
    ) -> ActionExecutionResult:
        """Execute via Supabase REST API."""
        from api.db import db_client

        if not organization_id:
            return ActionExecutionResult(
                action_id="database_query", action_type="database_query",
                success=False, message="Organization ID not available for Supabase query",
            )

        project_url = ""
        api_key = ""
        checked_keys: List[str] = []

        for key_name in (
            "integration_supabase",
            "composio_credentials_supabase",
            "service_credentials_supabase",
        ):
            config = await db_client.get_configuration(organization_id, key_name)
            if not config or not config.value:
                logger.debug(f"[SUPABASE] No config found for key '{key_name}'")
                continue

            checked_keys.append(key_name)
            raw_keys = list(config.value.keys()) if isinstance(config.value, dict) else []
            inner_creds = config.value.get("credentials", {}) if isinstance(config.value, dict) else {}
            inner_keys = list(inner_creds.keys()) if isinstance(inner_creds, dict) else []
            logger.info(
                f"[SUPABASE] Found config under '{key_name}': "
                f"top-level keys={raw_keys}, credentials keys={inner_keys}"
            )

            creds = self._extract_supabase_credentials(config.value)
            if creds["project_url"] and creds["api_key"]:
                project_url = creds["project_url"]
                api_key = creds["api_key"]
                logger.info(f"[SUPABASE] Using credentials from key '{key_name}'")
                break

            if creds["project_url"] and not project_url:
                project_url = creds["project_url"]
            if creds["api_key"] and not api_key:
                api_key = creds["api_key"]
            logger.warning(
                f"[SUPABASE] Incomplete credentials under key '{key_name}': "
                f"project_url={'set' if creds['project_url'] else 'EMPTY'}, "
                f"api_key={'set' if creds['api_key'] else 'EMPTY'}"
            )

        if not checked_keys:
            return ActionExecutionResult(
                action_id="database_query", action_type="database_query",
                success=False, message="Supabase credentials not configured. Go to Integrations to connect Supabase.",
            )

        if not project_url or not api_key:
            logger.error(
                f"[SUPABASE] Credentials found but incomplete across keys {checked_keys}: "
                f"project_url={'set' if project_url else 'EMPTY'}, "
                f"api_key={'set' if api_key else 'EMPTY'}"
            )
            return ActionExecutionResult(
                action_id="database_query", action_type="database_query",
                success=False,
                message="Supabase project URL or API key missing. Reconnect Supabase in Integrations and save both URL and key.",
            )

        headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

        # Auto-detect operation from SQL if set to generic "query"
        effective_operation = operation
        trimmed_sql = query_template.strip().upper() if query_template else ""
        if trimmed_sql.startswith("INSERT"):
            effective_operation = "insert"
        elif trimmed_sql.startswith("UPDATE"):
            effective_operation = "update"
        elif trimmed_sql.startswith("DELETE"):
            effective_operation = "delete"

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            if effective_operation == "query" or trimmed_sql.startswith("SELECT"):
                url = f"{project_url}/rest/v1/rpc/query"
                if table_name:
                    url = f"{project_url}/rest/v1/{table_name}?select=*"
                    if query_template and not query_template.strip().upper().startswith("SELECT"):
                        url += f"&{query_template}"

                async with session.get(url, headers=headers) as resp:
                    data = await resp.json() if resp.status < 400 else await resp.text()
                    if resp.status < 400:
                        return ActionExecutionResult(
                            action_id="database_query", action_type="database_query",
                            success=True, message=f"Query successful on {table_name}",
                            response_data={"data": data, "count": len(data) if isinstance(data, list) else 1},
                        )
                    return ActionExecutionResult(
                        action_id="database_query", action_type="database_query",
                        success=False, message=f"Supabase query failed: {data}",
                    )

            elif effective_operation == "insert" and table_name:
                url = f"{project_url}/rest/v1/{table_name}"
                body = self._parse_insert_body(query_template)
                logger.info(f"[SUPABASE] INSERT into {table_name}: body={body}")

                async with session.post(url, headers=headers, json=body) as resp:
                    data = await resp.json() if resp.status < 400 else await resp.text()
                    if resp.status < 400:
                        return ActionExecutionResult(
                            action_id="database_query", action_type="database_query",
                            success=True, message=f"Record inserted into {table_name}",
                            response_data={"data": data},
                        )
                    return ActionExecutionResult(
                        action_id="database_query", action_type="database_query",
                        success=False, message=f"Insert failed: {data}",
                    )

            else:
                return ActionExecutionResult(
                    action_id="database_query", action_type="database_query",
                    success=False, message=f"Operation '{effective_operation}' not yet supported for Supabase via REST API",
                )

    async def _execute_sql_via_webhook(
        self, db_type: str, query_template: str, table_name: str,
        organization_id: Optional[int] = None,
    ) -> ActionExecutionResult:
        """Execute SQL queries by sending to a configured webhook/proxy."""
        return ActionExecutionResult(
            action_id="database_query", action_type="database_query",
            success=False,
            message=f"Direct {db_type} query execution requires a database proxy. Configure a webhook endpoint for database queries.",
        )

    async def _execute_generic(
        self, db_type: str, operation: str, query_template: str, table_name: str,
    ) -> ActionExecutionResult:
        """Fallback for unsupported database types."""
        return ActionExecutionResult(
            action_id="database_query", action_type="database_query",
            success=False, message=f"Database type '{db_type}' not yet supported for direct execution",
        )


class ActionNodeExecutor:
    """
    Main executor for Action Node.
    Coordinates execution of multiple actions based on configuration.
    """

    def __init__(
        self,
        twilio_config: Optional[Dict[str, Any]] = None,
        email_config: Optional[Dict[str, Any]] = None,
        whatsapp_config: Optional[Dict[str, Any]] = None,
        slack_config: Optional[Dict[str, Any]] = None,
        organization_id: Optional[int] = None,
    ):
        """
        Initialize ActionNodeExecutor with service configurations.

        Args:
            twilio_config: Dict with account_sid, auth_token, from_number
            email_config: Dict with provider (sendgrid/smtp/mailgun), api_key/smtp settings
            whatsapp_config: Dict with provider (twilio/meta), account_sid, auth_token, from_number
            slack_config: Dict with bot_token, default_channel
            organization_id: Organization ID for database and integration queries
        """
        self.organization_id = organization_id
        self.twilio_executor = None
        self.email_executor = None
        self.whatsapp_executor = None
        self.slack_executor = None
        self.webhook_executor = WebhookExecutor()
        self.database_executor = DatabaseQueryExecutor()

        # Initialize Twilio SMS executor if config provided
        if twilio_config:
            self.twilio_executor = TwilioSmsExecutor(
                account_sid=twilio_config.get("account_sid", ""),
                auth_token=twilio_config.get("auth_token", ""),
                from_number=twilio_config.get("from_number"),
                messaging_service_sid=twilio_config.get("messaging_service_sid"),
            )

        # Initialize WhatsApp executor if config provided
        if whatsapp_config:
            provider = whatsapp_config.get("provider", "twilio")
            if provider == "twilio":
                self.whatsapp_executor = TwilioWhatsAppExecutor(
                    account_sid=whatsapp_config.get("account_sid", ""),
                    auth_token=whatsapp_config.get("auth_token", ""),
                    from_number=whatsapp_config.get("from_number", ""),
                )
            # Note: Meta WhatsApp API would need a different executor implementation

        # Initialize Slack executor if config provided
        if slack_config:
            self.slack_executor = SlackExecutor(
                bot_token=slack_config.get("bot_token", ""),
                default_channel=slack_config.get("default_channel"),
            )

        # Initialize email executor based on provider
        if email_config:
            provider = email_config.get("provider", "sendgrid")
            if provider == "sendgrid":
                self.email_executor = SendGridEmailExecutor(
                    api_key=email_config.get("api_key", ""),
                    from_email=email_config.get("from_email", ""),
                )
            elif provider == "mailgun":
                self.email_executor = MailgunEmailExecutor(
                    api_key=email_config.get("api_key", ""),
                    domain=email_config.get("domain", ""),
                    from_email=email_config.get("from_email", ""),
                    region=email_config.get("region", "us"),
                )
            elif provider == "smtp":
                self.email_executor = SmtpEmailExecutor(
                    smtp_host=email_config.get("smtp_host", ""),
                    smtp_port=email_config.get("smtp_port", 587),
                    username=email_config.get("username", ""),
                    password=email_config.get("password", ""),
                    from_email=email_config.get("from_email", ""),
                    use_tls=email_config.get("use_tls", True),
                )

    async def execute_action(
        self,
        action: ActionConfigDTO,
        variables: Dict[str, Any],
    ) -> ActionExecutionResult:
        """Execute a single action."""
        if not action.enabled:
            return ActionExecutionResult(
                action_id=action.id,
                action_type=action.type.value,
                success=True,
                message="Action skipped (disabled)",
            )

        logger.info(
            f"🔧 [ACTION] ▶ Executing action_id={action.id} "
            f"type={action.type.value} enabled={action.enabled}"
        )
        logger.debug(
            f"🔧 [ACTION] Config: to_number={getattr(action, 'to_number', None)}, "
            f"to_email={getattr(action, 'to_email', None)}, "
            f"subject={getattr(action, 'subject', None)}, "
            f"spreadsheet_id={getattr(action, 'spreadsheet_id', None)}, "
            f"sheet_name={getattr(action, 'sheet_name', None)}, "
            f"operation={getattr(action, 'operation', None)}, "
            f"database_service={getattr(action, 'database_service', None)}, "
            f"webhook_url={getattr(action, 'webhook_url', None)}"
        )
        logger.debug(
            f"🔧 [ACTION] Variables available: {list(variables.keys())}"
        )
        logger.debug(
            f"🔧 [ACTION] Variable values: "
            f"{{{', '.join(f'{k}={repr(v)[:80]}' for k, v in variables.items())}}}"
        )

        try:
            if action.type == ActionTypeEnum.send_sms:
                if not self.twilio_executor:
                    return ActionExecutionResult(
                        action_id=action.id,
                        action_type="send_sms",
                        success=False,
                        message="SMS not configured - Twilio credentials required",
                    )
                return await self.twilio_executor.send_sms(
                    to_number=action.to_number or "",
                    message=action.message or "",
                    variables=variables,
                )

            elif action.type == ActionTypeEnum.send_email:
                # Try direct email first, fall back to Composio Gmail
                if self.email_executor:
                    return await self.email_executor.send_email(
                        to_email=action.to_email or "",
                        subject=action.subject or "",
                        body=action.body or "",
                        is_html=action.is_html or False,
                        variables=variables,
                    )
                # Fallback: try Composio Gmail OAuth connection
                if self.organization_id:
                    try:
                        from api.services.integrations.composio_service import composio_service
                        to_email = substitute_variables(action.to_email or "", variables)
                        subject = substitute_variables(action.subject or "", variables)
                        body = substitute_variables(action.body or "", variables)
                        result = await composio_service.execute_action(
                            organization_id=self.organization_id,
                            app_id="gmail",
                            action_name="GMAIL_SEND_EMAIL",
                            params={"recipient_email": to_email, "subject": subject, "body": body, "message_body": body},
                        )
                        if result.success:
                            return ActionExecutionResult(
                                action_id=action.id, action_type="send_email",
                                success=True, message=f"Email sent via Gmail to {to_email}",
                                response_data=result.data,
                            )
                        logger.warning(f"Composio Gmail fallback failed: {result.error}")
                    except Exception as e:
                        logger.warning(f"Composio Gmail fallback error: {e}")
                return ActionExecutionResult(
                    action_id=action.id, action_type="send_email",
                    success=False,
                    message="Email not configured. Set up email credentials in Settings, or connect Gmail from Integrations.",
                )

            elif action.type == ActionTypeEnum.send_whatsapp:
                if not self.whatsapp_executor:
                    return ActionExecutionResult(
                        action_id=action.id,
                        action_type="send_whatsapp",
                        success=False,
                        message="WhatsApp not configured - WhatsApp credentials required",
                    )
                return await self.whatsapp_executor.send_message(
                    to_number=action.to_number or "",
                    message=action.message or "",
                    variables=variables,
                )

            elif action.type == ActionTypeEnum.send_slack:
                # Try direct Slack first, fall back to Composio Slack OAuth
                if self.slack_executor:
                    return await self.slack_executor.send_message(
                        channel=action.channel or "",
                        message=action.message or "",
                        variables=variables,
                    )
                # Fallback: try Composio Slack OAuth connection
                if self.organization_id:
                    try:
                        from api.services.integrations.composio_service import composio_service
                        channel = substitute_variables(action.channel or "#general", variables)
                        message = substitute_variables(action.message or "", variables)
                        result = await composio_service.execute_action(
                            organization_id=self.organization_id,
                            app_id="slack",
                            action_name="SLACK_SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL",
                            params={"channel": channel, "text": message},
                        )
                        if result.success:
                            return ActionExecutionResult(
                                action_id=action.id, action_type="send_slack",
                                success=True, message=f"Slack message sent to {channel} via Composio",
                                response_data=result.data,
                            )
                        logger.warning(f"Composio Slack fallback failed: {result.error}")
                    except Exception as e:
                        logger.warning(f"Composio Slack fallback error: {e}")
                return ActionExecutionResult(
                    action_id=action.id, action_type="send_slack",
                    success=False,
                    message="Slack not configured. Set up Slack credentials in Settings, or connect Slack from Integrations.",
                )

            elif action.type in (ActionTypeEnum.webhook, ActionTypeEnum.api_call):
                return await self.webhook_executor.execute(
                    url=action.url or "",
                    method=action.method or "POST",
                    headers=action.headers,
                    body_template=action.body_template,
                    timeout_seconds=action.timeout_seconds or 30,
                    variables=variables,
                )

            elif action.type == ActionTypeEnum.set_variable:
                # Set variable just stores value in variables dict
                var_name = action.variable_name or ""
                value = substitute_variables(action.value or "", variables)

                # Type conversion based on value_type
                if action.value_type == "number":
                    try:
                        value = float(value)
                    except ValueError:
                        pass
                elif action.value_type == "boolean":
                    value = value.lower() in ("true", "1", "yes")
                elif action.value_type == "json":
                    try:
                        value = json.loads(value)
                    except json.JSONDecodeError:
                        pass

                variables[var_name] = value
                return ActionExecutionResult(
                    action_id=action.id,
                    action_type="set_variable",
                    success=True,
                    message=f"Variable '{var_name}' set",
                    response_data={"variable": var_name, "value": value},
                )

            elif action.type == ActionTypeEnum.database_query:
                return await self.database_executor.execute(
                    database_service=action.database_service or "",
                    operation=action.operation or "query",
                    query_template=action.query_template or "",
                    table_name=action.table_name or "",
                    variables=variables,
                    organization_id=self.organization_id,
                )

            elif action.type == ActionTypeEnum.schedule_meeting:
                try:
                    from api.services.integrations.composio_service import composio_service
                    if not self.organization_id:
                        return ActionExecutionResult(
                            action_id=action.id, action_type="schedule_meeting",
                            success=False, message="Organization ID not available for Google Calendar",
                        )
                    event_title = substitute_variables(action.event_title or "", variables)
                    attendee_email = substitute_variables(action.attendee_email or "", variables)
                    start_time = substitute_variables(action.start_time or "", variables)
                    end_time = substitute_variables(action.end_time or "", variables)
                    description = substitute_variables(getattr(action, 'description', '') or "", variables)
                    location = substitute_variables(action.location or "", variables)
                    timezone = action.timezone or "UTC"

                    logger.info(
                        f"📅 [CALENDAR ACTION] Creating event: {event_title}, "
                        f"attendee={attendee_email}, start={start_time}, end={end_time}"
                    )

                    params = {
                        "summary": event_title,
                        "description": description,
                        "start_datetime": start_time,
                        "end_datetime": end_time,
                        "timezone": timezone,
                        "attendees": [attendee_email] if attendee_email else [],
                        "location": location,
                        "send_updates": "all" if action.send_notifications else "none",
                    }
                    result = await composio_service.execute_action(
                        organization_id=self.organization_id,
                        app_id="googlecalendar",
                        action_name="GOOGLECALENDAR_CREATE_EVENT",
                        params=params,
                    )
                    if result.success:
                        logger.info(f"📅 [CALENDAR ACTION] ✅ Event created: {result.data}")
                        return ActionExecutionResult(
                            action_id=action.id, action_type="schedule_meeting",
                            success=True, message=f"Meeting '{event_title}' scheduled with {attendee_email}",
                            response_data=result.data,
                        )
                    logger.error(f"📅 [CALENDAR ACTION] ❌ Failed: {result.error}")
                    return ActionExecutionResult(
                        action_id=action.id, action_type="schedule_meeting",
                        success=False, message=f"Google Calendar failed: {result.error}",
                    )
                except Exception as e:
                    logger.error(f"📅 [CALENDAR ACTION] ❌ Exception: {e}", exc_info=True)
                    return ActionExecutionResult(
                        action_id=action.id, action_type="schedule_meeting",
                        success=False, message=f"Google Calendar error: {str(e)}",
                    )

            elif action.type == ActionTypeEnum.google_sheets:
                try:
                    from api.services.integrations.composio_service import composio_service
                    if not self.organization_id:
                        return ActionExecutionResult(
                            action_id=action.id, action_type="google_sheets",
                            success=False, message="Organization ID not available for Google Sheets",
                        )
                    spreadsheet_id = action.spreadsheet_id or ""
                    sheet_name = action.sheet_name or "Sheet1"
                    if variables:
                        spreadsheet_id = substitute_variables(spreadsheet_id, variables)
                        sheet_name = substitute_variables(sheet_name, variables)

                    logger.info(
                        f"📊 [SHEETS ACTION] op={action.operation}, "
                        f"spreadsheet_id={spreadsheet_id}, sheet_name={sheet_name}"
                    )

                    if not spreadsheet_id:
                        logger.error("📊 [SHEETS ACTION] ❌ Missing spreadsheet_id")
                        return ActionExecutionResult(
                            action_id=action.id, action_type="google_sheets",
                            success=False,
                            message="Google Sheets action is missing a Spreadsheet ID. Open the action and paste the ID from your sheet URL (between /d/ and /edit).",
                        )

                    if action.operation == "read" or action.operation == "query":
                        # GOOGLESHEETS_GET_SPREADSHEET_DATA is deprecated; use VALUES_GET.
                        params = {
                            "spreadsheet_id": spreadsheet_id,
                            "range": f"{sheet_name}!A1:Z1000",
                        }
                        logger.info(f"📊 [SHEETS ACTION] READ params: {params}")
                        result = await composio_service.execute_action(
                            organization_id=self.organization_id, app_id="googlesheets",
                            action_name="GOOGLESHEETS_VALUES_GET",
                            params=params,
                        )
                    else:
                        raw_mapping = action.data_mapping or {}
                        logger.info(
                            f"📊 [SHEETS ACTION] Raw data_mapping from config: {raw_mapping}"
                        )
                        data_mapping = dict(raw_mapping)
                        if variables:
                            data_mapping = {k: substitute_variables(v, variables) for k, v in data_mapping.items()}
                        logger.info(
                            f"📊 [SHEETS ACTION] Resolved data_mapping: {data_mapping}"
                        )

                        # Build a single ordered row from the column->value mapping.
                        # Keys are spreadsheet column letters (A, B, ...); order by
                        # column index and pad gaps so values land in the right column.
                        def _col_index(letter: str):
                            letter = (letter or "").strip().upper()
                            if not letter:
                                return None
                            idx = 0
                            for ch in letter:
                                if "A" <= ch <= "Z":
                                    idx = idx * 26 + (ord(ch) - ord("A") + 1)
                                else:
                                    return None
                            return idx - 1

                        indices = {k: _col_index(k) for k in data_mapping}
                        if data_mapping and all(v is not None for v in indices.values()):
                            max_idx = max(indices.values())
                            row_values = ["" for _ in range(max_idx + 1)]
                            for k, val in data_mapping.items():
                                row_values[indices[k]] = val if val is not None else ""
                        else:
                            row_values = [
                                (v if v is not None else "")
                                for v in data_mapping.values()
                            ]

                        if action.operation == "update":
                            # Overwrite a specific range. GOOGLESHEETS_VALUES_UPDATE
                            # (snake_case params) replaces the deprecated BATCH_UPDATE.
                            update_range = action.range or f"{sheet_name}!A1"
                            params = {
                                "spreadsheet_id": spreadsheet_id,
                                "range": update_range,
                                "values": [row_values],
                                "value_input_option": "USER_ENTERED",
                            }
                            logger.info(f"📊 [SHEETS ACTION] UPDATE params: {params}")
                            result = await composio_service.execute_action(
                                organization_id=self.organization_id, app_id="googlesheets",
                                action_name="GOOGLESHEETS_VALUES_UPDATE",
                                params=params,
                            )
                        else:
                            # Append a new row at the end of the table.
                            # NOTE: this tool uses camelCase parameter names.
                            params = {
                                "spreadsheetId": spreadsheet_id,
                                "range": sheet_name,
                                "values": [row_values],
                                "valueInputOption": "USER_ENTERED",
                                "insertDataOption": "INSERT_ROWS",
                            }
                            logger.info(f"📊 [SHEETS ACTION] APPEND params: {params}")
                            result = await composio_service.execute_action(
                                organization_id=self.organization_id, app_id="googlesheets",
                                action_name="GOOGLESHEETS_SPREADSHEETS_VALUES_APPEND",
                                params=params,
                            )

                    if result.success:
                        logger.info(f"📊 [SHEETS ACTION] ✅ Success: {result.data}")
                        return ActionExecutionResult(
                            action_id=action.id, action_type="google_sheets",
                            success=True, message=f"Google Sheets {action.operation} successful",
                            response_data=result.data,
                        )
                    logger.error(f"📊 [SHEETS ACTION] ❌ Failed: {result.error}")
                    return ActionExecutionResult(
                        action_id=action.id, action_type="google_sheets",
                        success=False, message=f"Google Sheets failed: {result.error}",
                    )
                except Exception as e:
                    logger.error(f"📊 [SHEETS ACTION] ❌ Exception: {e}", exc_info=True)
                    return ActionExecutionResult(
                        action_id=action.id, action_type="google_sheets",
                        success=False, message=f"Google Sheets error: {str(e)}",
                    )

            else:
                return ActionExecutionResult(
                    action_id=action.id,
                    action_type=str(action.type),
                    success=False,
                    message=f"Unknown action type: {action.type}",
                )

        except Exception as e:
            logger.error(f"Error executing action {action.id}: {e}")
            return ActionExecutionResult(
                action_id=action.id,
                action_type=str(action.type),
                success=False,
                message=f"Action execution error: {str(e)}",
            )

    async def execute_actions(
        self,
        actions: List[ActionConfigDTO],
        variables: Dict[str, Any],
        execution_mode: str = "sequential",
        stop_on_error: bool = False,
    ) -> List[ActionExecutionResult]:
        """
        Execute multiple actions.

        Args:
            actions: List of actions to execute
            variables: Variables available for substitution
            execution_mode: 'sequential' or 'parallel'
            stop_on_error: Stop execution on first error (sequential mode only)

        Returns:
            List of ActionExecutionResult
        """
        results = []

        if execution_mode == "parallel":
            # Execute all actions in parallel
            tasks = [self.execute_action(action, variables) for action in actions]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Convert exceptions to results
            final_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    final_results.append(
                        ActionExecutionResult(
                            action_id=actions[i].id,
                            action_type=str(actions[i].type),
                            success=False,
                            message=f"Execution error: {str(result)}",
                        )
                    )
                else:
                    final_results.append(result)
            results = final_results
        else:
            # Execute actions sequentially
            for action in actions:
                result = await self.execute_action(action, variables)
                results.append(result)

                if stop_on_error and not result.success:
                    logger.warning(
                        f"Stopping action execution due to error in {action.id}"
                    )
                    break

        return results

