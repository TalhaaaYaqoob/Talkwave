from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class NodeType(str, Enum):
    startNode = "startCall"
    endNode = "endCall"
    agentNode = "agentNode"
    globalNode = "globalNode"
    actionNode = "actionNode"
    callVariables = "callVariables"
    ifElse = "ifElse"
    categorize = "categorize"
    transfer = "transfer"
    meetingTrigger = "meetingTrigger"
    meetingSummary = "meetingSummary"


class Position(BaseModel):
    x: float
    y: float


class VariableType(str, Enum):
    string = "string"
    number = "number"
    boolean = "boolean"


class ExtractionVariableDTO(BaseModel):
    name: str = Field(..., min_length=1)
    type: VariableType
    prompt: Optional[str] = None
    # Critical variables must be collected from the caller before the node can
    # transition; optional ones are still extracted but never block the flow.
    # Defaults to True so existing workflows keep their current gating behavior.
    required: bool = True


# =====================
# Agent Step Tool DTOs
# =====================


class ToolTypeEnum(str, Enum):
    http_request = "http_request"
    webhook = "webhook"
    database_query = "database_query"
    custom_code = "custom_code"
    integration = "integration"


class InputSchemaPropertyDTO(BaseModel):
    type: str
    description: Optional[str] = None


class InputSchemaDTO(BaseModel):
    type: str = "object"
    properties: Dict[str, InputSchemaPropertyDTO] = Field(default_factory=dict)
    required: Optional[List[str]] = None


class InlineToolConfigDTO(BaseModel):
    name: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    tool_type: ToolTypeEnum
    configuration: Dict[str, Any] = Field(default_factory=dict)
    input_schema: InputSchemaDTO = Field(default_factory=InputSchemaDTO)
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class AgentToolReferenceDTO(BaseModel):
    id: str = Field(..., min_length=1)
    type: str = Field(..., pattern="^(existing|inline|integration)$")
    # For existing tools
    tool_id: Optional[int] = None
    tool_name: Optional[str] = None
    tool_display_name: Optional[str] = None
    llm_description: Optional[str] = None
    # For inline tools
    inline_config: Optional[InlineToolConfigDTO] = None
    # For integration tools
    integration_type: Optional[str] = None
    composio_app_id: Optional[str] = None
    # Integration-specific configs (matches frontend types)
    twilio_sms: Optional[Dict[str, Any]] = None
    google_sheets: Optional[Dict[str, Any]] = None
    email: Optional[Dict[str, Any]] = None
    mcp_server: Optional[Dict[str, Any]] = None
    function: Optional[Dict[str, Any]] = None
    api: Optional[Dict[str, Any]] = None


# =====================
# Exit Condition DTOs
# =====================


class ExitConditionVariableDTO(BaseModel):
    name: str = Field(..., min_length=1)
    type: VariableType
    description: str = Field(..., min_length=1)


class ExitConditionDTO(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    llm_description: str = Field(..., min_length=1)
    required_variables: List[ExitConditionVariableDTO] = Field(default_factory=list)


# =====================
# Knowledge Base DTOs
# =====================


class KnowledgeBaseConfigDTO(BaseModel):
    enabled: bool = False
    llm_description: Optional[str] = None
    query_override: Optional[str] = None
    chunk_limit: int = Field(default=3, ge=1, le=10)


# =====================
# Action Node DTOs
# =====================


class ActionTypeEnum(str, Enum):
    send_sms = "send_sms"
    send_email = "send_email"
    send_whatsapp = "send_whatsapp"
    send_slack = "send_slack"
    google_sheets = "google_sheets"
    schedule_meeting = "schedule_meeting"
    webhook = "webhook"
    api_call = "api_call"
    set_variable = "set_variable"
    database_query = "database_query"


class BaseActionConfigDTO(BaseModel):
    id: str = Field(..., min_length=1)
    type: ActionTypeEnum
    name: str = Field(..., min_length=1)
    enabled: bool = True
    continue_on_error: bool = False


class SendSmsActionDTO(BaseActionConfigDTO):
    type: ActionTypeEnum = ActionTypeEnum.send_sms
    to_number: str = ""
    message: str = ""


class SendEmailActionDTO(BaseActionConfigDTO):
    type: ActionTypeEnum = ActionTypeEnum.send_email
    to_email: str = ""
    subject: str = ""
    body: str = ""
    is_html: bool = False


class SendWhatsAppActionDTO(BaseActionConfigDTO):
    type: ActionTypeEnum = ActionTypeEnum.send_whatsapp
    to_number: str = ""
    message: str = ""


class SendSlackActionDTO(BaseActionConfigDTO):
    type: ActionTypeEnum = ActionTypeEnum.send_slack
    channel: str = ""
    message: str = ""


class DatabaseQueryActionDTO(BaseActionConfigDTO):
    type: ActionTypeEnum = ActionTypeEnum.database_query
    database_service: str = ""  # postgresql, mysql, mongodb, supabase, firebase
    operation: str = "query"  # query, insert, update, delete
    query_template: str = ""
    table_name: Optional[str] = None
    description: Optional[str] = None
    ai_explanation: Optional[str] = None
    parameters: Dict[str, str] = Field(default_factory=dict)
    result_variable: Optional[str] = None


class GoogleSheetsActionDTO(BaseActionConfigDTO):
    type: ActionTypeEnum = ActionTypeEnum.google_sheets
    operation: str = "append"  # append, update, read
    spreadsheet_id: str = ""
    sheet_name: str = "Sheet1"
    range: Optional[str] = None
    data_mapping: Dict[str, str] = Field(default_factory=dict)


class ScheduleMeetingActionDTO(BaseActionConfigDTO):
    type: ActionTypeEnum = ActionTypeEnum.schedule_meeting
    event_title: str = ""
    attendee_email: str = ""
    start_time: str = ""
    end_time: str = ""
    description: str = ""
    location: str = ""
    timezone: str = "UTC"
    send_notifications: bool = True


class WebhookActionDTO(BaseActionConfigDTO):
    type: ActionTypeEnum = ActionTypeEnum.webhook
    url: str = ""
    method: str = "POST"
    headers: Dict[str, str] = Field(default_factory=dict)
    body_template: Optional[str] = None
    timeout_seconds: int = 30


class ApiCallActionDTO(BaseActionConfigDTO):
    type: ActionTypeEnum = ActionTypeEnum.api_call
    url: str = ""
    method: str = "GET"
    headers: Dict[str, str] = Field(default_factory=dict)
    body_template: Optional[str] = None
    response_variable: Optional[str] = None
    timeout_seconds: int = 30


class SetVariableActionDTO(BaseActionConfigDTO):
    type: ActionTypeEnum = ActionTypeEnum.set_variable
    variable_name: str = ""
    value: str = ""
    value_type: str = "string"  # string, number, boolean, json


# Generic action config that accepts any action type
class ActionConfigDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., min_length=1)
    type: ActionTypeEnum
    name: str = Field(..., min_length=1)
    enabled: bool = True
    continue_on_error: bool = False
    # SMS fields
    to_number: Optional[str] = None
    message: Optional[str] = None
    # Email fields
    to_email: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    is_html: Optional[bool] = None
    # Google Sheets fields
    operation: Optional[str] = None
    spreadsheet_id: Optional[str] = None
    sheet_name: Optional[str] = None
    range: Optional[str] = None
    data_mapping: Optional[Dict[str, str]] = None
    # Webhook/API fields
    url: Optional[str] = None
    method: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    body_template: Optional[str] = None
    timeout_seconds: Optional[int] = None
    response_variable: Optional[str] = None
    # Set Variable fields
    variable_name: Optional[str] = None
    value: Optional[str] = None
    value_type: Optional[str] = None
    # Schedule Meeting fields
    event_title: Optional[str] = None
    attendee_email: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = None
    timezone: Optional[str] = None
    send_notifications: Optional[bool] = None
    # Slack fields
    channel: Optional[str] = None
    # Database query fields
    database_service: Optional[str] = None
    query_template: Optional[str] = None
    table_name: Optional[str] = None
    description: Optional[str] = None
    ai_explanation: Optional[str] = None
    parameters: Optional[Dict[str, str]] = None
    result_variable: Optional[str] = None

    @field_validator("body_template", mode="before")
    @classmethod
    def coerce_body_template(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str):
            return v
        # Non-string (dict, list, int) → serialize to JSON string
        import json
        try:
            return json.dumps(v)
        except Exception:
            return str(v)


class NodeDataDTO(BaseModel):
    name: str = Field(..., min_length=1)
    # prompt is optional for Action Nodes
    prompt: Optional[str] = Field(default=None)
    is_static: bool = False
    is_start: bool = False
    is_end: bool = False
    # Voice calls are conversational: the caller should be able to break
    # in whenever the agent is talking. ``False`` is reserved for nodes
    # where uninterruptible playback is genuinely desired (end-of-call
    # voicemails, legal disclosures, etc.) and must be opted in to.
    allow_interrupt: bool = True
    extraction_enabled: bool = False
    extraction_prompt: Optional[str] = None
    extraction_variables: Optional[list[ExtractionVariableDTO]] = None
    add_global_prompt: bool = True
    wait_for_user_response: bool = False
    wait_for_user_response_timeout: Optional[float] = None
    detect_voicemail: bool = True
    delayed_start: bool = False
    delayed_start_duration: Optional[float] = None
    connection_greeting: Optional[str] = None
    # Web search feature
    web_search_enabled: bool = False
    # Enhanced Agent Step fields
    tools: Optional[List[AgentToolReferenceDTO]] = None
    exit_conditions: Optional[List[ExitConditionDTO]] = None
    knowledge_base: Optional[KnowledgeBaseConfigDTO] = None
    # Conversation constraints (Timer / Burst behavior on agent nodes)
    timer_duration: Optional[int] = None
    max_rounds: Optional[int] = None
    # If/Else node
    condition_text: Optional[str] = None
    # Categorize node
    categories: Optional[List[str]] = None
    # Transfer node
    transfer_target: Optional[str] = None
    is_literal: bool = False
    # Action Node fields
    description: Optional[str] = None
    actions: Optional[List[ActionConfigDTO]] = None
    execution_mode: Optional[str] = "sequential"
    stop_on_error: Optional[bool] = False
    # Meeting node fields
    trigger_config: Optional[Dict[str, Any]] = None
    response_prompt: Optional[str] = None
    summary_config: Optional[Dict[str, Any]] = None
    output_format: Optional[str] = None


class RFNodeDTO(BaseModel):
    id: str
    type: NodeType = Field(default=NodeType.agentNode)
    position: Position
    data: NodeDataDTO


class EdgeDataDTO(BaseModel):
    label: str = Field(default="", description="Optional label for the edge")
    condition: str = Field(default="", description="Optional condition for edge transition")


class RFEdgeDTO(BaseModel):
    id: str
    source: str
    target: str
    data: EdgeDataDTO


class EdgeConditionError:
    """Represents a missing edge condition error."""
    def __init__(self, edge_id: str, source_name: str, target_name: str):
        self.edge_id = edge_id
        self.source_name = source_name
        self.target_name = target_name
        self.message = f"Condition required: '{source_name}' → '{target_name}'"


class ReactFlowDTO(BaseModel):
    nodes: List[RFNodeDTO]
    edges: List[RFEdgeDTO]

    @model_validator(mode="after")
    def _referential_integrity(self):
        node_ids = {n.id for n in self.nodes}
        line_errors: list[dict[str, str]] = []

        for idx, edge in enumerate(self.edges):
            for endpoint in (edge.source, edge.target):
                if endpoint not in node_ids:
                    line_errors.append(
                        dict(
                            loc=("edges", idx),
                            type="missing_node",
                            msg="Edge references missing node",
                            input=edge.model_dump(mode="python"),
                            ctx={"edge_id": edge.id, "endpoint": endpoint},
                        )
                    )

        if line_errors:
            raise ValidationError.from_exception_data(
                title="ReactFlowDTO validation failed",
                line_errors=line_errors,
            )

        return self

    def validate_edge_conditions(self) -> List[EdgeConditionError]:
        """
        Validate that edges from startNode and agentNode have non-empty conditions.
        Returns a list of EdgeConditionError for edges missing conditions.
        Meeting workflows are exempt — edges to meetingSummary or from
        meetingTrigger don't require conditions.
        """
        errors: List[EdgeConditionError] = []
        node_types = {n.id: n.type for n in self.nodes}
        node_names = {n.id: n.data.name for n in self.nodes}

        is_meeting = any(n.type == NodeType.meetingTrigger for n in self.nodes)

        for edge in self.edges:
            source_type = node_types.get(edge.source)
            target_type = node_types.get(edge.target)

            if source_type in (NodeType.startNode, NodeType.agentNode):
                if is_meeting and target_type in (NodeType.meetingSummary, NodeType.meetingTrigger):
                    continue
                if is_meeting and source_type == NodeType.agentNode and len([
                    e for e in self.edges if e.source == edge.source
                ]) <= 1:
                    continue

                condition = (edge.data.condition or "").strip()
                if not condition:
                    source_name = node_names.get(edge.source, edge.source)
                    target_name = node_names.get(edge.target, edge.target)
                    errors.append(EdgeConditionError(
                        edge_id=edge.id,
                        source_name=source_name,
                        target_name=target_name,
                    ))

        return errors
