export enum NodeType {
    START_CALL = 'startCall',
    AGENT_NODE = 'agentNode',
    END_CALL = 'endCall',
    GLOBAL_NODE = 'globalNode',
    ACTION_NODE = 'actionNode',
    CALL_VARIABLES = 'callVariables',
    MEETING_TRIGGER = 'meetingTrigger',
    MEETING_SUMMARY = 'meetingSummary',
    IF_ELSE = 'ifElse',
    CATEGORIZE = 'categorize',
    TRANSFER = 'transfer',
}

export type ExtractionVariable = {
    name: string;
    type: 'string' | 'number' | 'boolean';
    prompt?: string;
    // Critical variables must be collected before the node transitions; optional
    // ones are still extracted but never block the conversation. Defaults to
    // required when unset (matches legacy behavior).
    required?: boolean;
};

// Tool Types for custom tools
export type ToolType = 'http_request' | 'webhook' | 'database_query' | 'custom_code' | 'integration';

// Inline Tool Configuration
export interface InlineToolConfig {
    name: string;
    display_name: string;
    description: string;
    tool_type: ToolType;
    configuration: Record<string, unknown>;
    input_schema: {
        type: string;
        properties: Record<string, { type: string; description?: string }>;
        required?: string[];
    };
    timeout_seconds: number;
}

// Integration Tool Types
export type IntegrationToolType =
    | 'twilio_sms'
    | 'google_sheets'
    | 'google_calendar'
    | 'email'
    | 'mcp_server'
    | 'function'
    | 'api';

// Twilio SMS Configuration
export interface TwilioSmsConfig {
    enabled: boolean;
    description: string;
    to_number_source: 'context' | 'static';
    to_number?: string;
    to_number_variable?: string;
    message_template: string;
    use_conversation_context?: boolean;
}

// Google Sheets Configuration
export interface GoogleSheetsConfig {
    enabled: boolean;
    description: string;
    operation: 'read' | 'append' | 'update';
    spreadsheet_id?: string;
    sheet_name?: string;
    range?: string;
    data_mapping?: Record<string, string>;
}

// Google Calendar Configuration
export interface GoogleCalendarConfig {
    enabled: boolean;
    description: string;
}

// Email Configuration
export interface EmailConfig {
    enabled: boolean;
    description: string;
    to_email_source: 'context' | 'static';
    to_email?: string;
    to_email_variable?: string;
    subject_template: string;
    body_template: string;
    use_html?: boolean;
}

// MCP Server Configuration
export interface McpServerConfig {
    enabled: boolean;
    description: string;
    server_name: string;
    server_url: string;
    tools: string[];
    auth_type?: 'none' | 'bearer' | 'api_key';
    auth_token?: string;
}

// Function Calling Configuration
export interface FunctionConfig {
    enabled: boolean;
    name: string;
    display_name: string;
    description: string;
    parameters: {
        type: 'object';
        properties: Record<string, {
            type: string;
            description: string;
            enum?: string[];
        }>;
        required: string[];
    };
    handler_type: 'webhook' | 'inline_response';
    webhook_url?: string;
    response_template?: string;
}

// API Tool Configuration
export interface ApiToolConfig {
    enabled: boolean;
    name: string;
    display_name: string;
    description: string;
    method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
    url: string;
    headers?: Record<string, string>;
    body_template?: string;
    input_schema: {
        type: 'object';
        properties: Record<string, { type: string; description?: string }>;
        required?: string[];
    };
    response_path?: string;
    timeout_seconds: number;
}

// Agent Tool Reference - links to custom tools or integration tools
export interface AgentToolReference {
    id: string;
    type: 'existing' | 'inline' | 'integration';
    // For existing tools from library
    tool_id?: number;
    tool_name?: string;
    tool_display_name?: string;
    llm_description?: string;
    // For inline tools
    inline_config?: InlineToolConfig;
    // For integration tools
    integration_type?: IntegrationToolType;
    composio_app_id?: string;
    twilio_sms?: TwilioSmsConfig;
    google_sheets?: GoogleSheetsConfig;
    google_calendar?: GoogleCalendarConfig;
    email?: EmailConfig;
    mcp_server?: McpServerConfig;
    function?: FunctionConfig;
    api?: ApiToolConfig;
}

// Exit Condition Variable
export interface ExitConditionVariable {
    name: string;
    type: 'string' | 'number' | 'boolean';
    description: string;
}

// Exit Condition - defines when to exit the agent and route elsewhere
export interface ExitCondition {
    id: string;
    name: string;
    description?: string;
    llm_description?: string;
    required_variables?: ExitConditionVariable[];
}

// Knowledge Base Configuration
export interface KnowledgeBaseConfig {
    enabled: boolean;
    llm_description?: string;
    query_override?: string;
    chunk_limit: number;
}

// Default values for Knowledge Base
export const DEFAULT_KNOWLEDGE_BASE_CONFIG: KnowledgeBaseConfig = {
    enabled: false,
    llm_description: '',
    query_override: '',
    chunk_limit: 3,
};

export type FlowNodeData = {
    prompt?: string;
    name: string;
    is_start?: boolean;
    is_static?: boolean;
    is_end?: boolean;
    invalid?: boolean;
    invalidField?: string | null;
    validationMessage?: string | null;
    selected_through_edge?: boolean;
    hovered_through_edge?: boolean;
    allow_interrupt?: boolean;
    extraction_enabled?: boolean;
    extraction_prompt?: string;
    extraction_variables?: ExtractionVariable[];
    add_global_prompt?: boolean;
    wait_for_user_greeting?: boolean;
    detect_voicemail?: boolean;
    delayed_start?: boolean;
    delayed_start_duration?: number;
    connection_greeting?: string;
    web_search_enabled?: boolean;
    tools?: AgentToolReference[];
    exit_conditions?: ExitCondition[];
    knowledge_base?: KnowledgeBaseConfig;
    // Agent node conversation constraints (Timer/Burst behavior)
    timer_duration?: number;
    max_rounds?: number;
    // If/Else node
    condition_text?: string;
    // Categorize node
    categories?: string[];
    // Transfer node
    transfer_target?: string;
    is_literal?: boolean;
}

export type FlowNode = {
    id: string;
    type: string;
    position: { x: number; y: number };
    data: FlowNodeData;
    measured?: {
        width: number;
        height: number;
    };
    selected?: boolean;
    dragging?: boolean;
};

export type FlowEdgeData = {
    condition: string;
    label: string;
    invalid?: boolean;
    validationMessage?: string | null;
}

export type FlowEdge = {
    id: string;
    source: string;
    target: string;
    type?: string;
    data: FlowEdgeData;
    animated?: boolean;
    invalid?: boolean;
};

export interface WorkflowDefinition {
    nodes: FlowNode[];
    edges: FlowEdge[];
    viewport: {
        x: number;
        y: number;
        zoom: number;
    };
}

export interface WorkflowData {
    name: string;
    workflow_definition: WorkflowDefinition;
}

export type WorkflowValidationError = {
    kind: 'node' | 'edge' | 'workflow';
    id: string;
    field: string;
    message: string;
}

// =============================================================================
// Action Node Types - For post-conversation actions
// =============================================================================

export type ActionType =
    | 'send_sms'
    | 'send_email'
    | 'send_whatsapp'
    | 'send_slack'
    | 'google_sheets'
    | 'schedule_meeting'
    | 'webhook'
    | 'api_call'
    | 'set_variable'
    | 'database_query'
    | 'custom_tool';

// Base action configuration
export interface BaseActionConfig {
    id: string;
    type: ActionType;
    name: string;
    enabled: boolean;
    continue_on_error?: boolean;
}

// Send SMS Action
export interface SendSmsAction extends BaseActionConfig {
    type: 'send_sms';
    to_number: string; // Can use {{variable}} syntax
    message: string;   // Can use {{variable}} syntax
}

// Send Email Action
export interface SendEmailAction extends BaseActionConfig {
    type: 'send_email';
    to_email: string;     // Can use {{variable}} syntax
    subject: string;      // Can use {{variable}} syntax
    body: string;         // Can use {{variable}} syntax
    is_html?: boolean;
}

// Send WhatsApp Action
export interface SendWhatsAppAction extends BaseActionConfig {
    type: 'send_whatsapp';
    to_number: string; // Can use {{variable}} syntax
    message: string;   // Can use {{variable}} syntax
}

// Send Slack Action
export interface SendSlackAction extends BaseActionConfig {
    type: 'send_slack';
    channel: string;   // Channel name or ID
    message: string;   // Can use {{variable}} syntax
}

// Database Query Action
export interface DatabaseQueryAction extends BaseActionConfig {
    type: 'database_query';
    database_service: string; // postgresql, mysql, mongodb, supabase, firebase
    operation: 'query' | 'insert' | 'update' | 'delete';
    query_template: string;
    table_name?: string;
    description?: string;
    ai_explanation?: string;
    parameters?: Record<string, string>;
    result_variable?: string;
}

// Google Sheets Action
export interface GoogleSheetsAction extends BaseActionConfig {
    type: 'google_sheets';
    operation: 'append' | 'update' | 'read';
    spreadsheet_id: string;
    sheet_name: string;
    range?: string;
    data_mapping: Record<string, string>; // column -> {{variable}} mapping
}

// Schedule Meeting Action (Google Calendar)
export interface ScheduleMeetingAction extends BaseActionConfig {
    type: 'schedule_meeting';
    event_title: string;
    attendee_email: string;
    start_time: string;
    end_time: string;
    description?: string;
    location?: string;
    timezone: string;
    send_notifications?: boolean;
}

// Webhook Action
export interface WebhookAction extends BaseActionConfig {
    type: 'webhook';
    url: string;
    method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
    headers?: Record<string, string>;
    body_template?: string; // JSON template with {{variable}} syntax
    timeout_seconds?: number;
}

// API Call Action
export interface ApiCallAction extends BaseActionConfig {
    type: 'api_call';
    url: string;
    method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
    headers?: Record<string, string>;
    body_template?: string;
    response_variable?: string; // Store response in this variable
    timeout_seconds?: number;
}

// Set Variable Action
export interface SetVariableAction extends BaseActionConfig {
    type: 'set_variable';
    variable_name: string;
    value: string; // Can use {{variable}} syntax or static value
    value_type: 'string' | 'number' | 'boolean' | 'json';
}

// Custom Tool Action (from custom tools library)
export interface CustomToolAction extends BaseActionConfig {
    type: 'custom_tool';
    tool_id: number;
    tool_name: string;
    input_data?: Record<string, string>; // key -> {{variable}} or static value
}

// Union type for all actions
export type ActionConfig =
    | SendSmsAction
    | SendEmailAction
    | SendWhatsAppAction
    | SendSlackAction
    | DatabaseQueryAction
    | GoogleSheetsAction
    | ScheduleMeetingAction
    | WebhookAction
    | ApiCallAction
    | SetVariableAction
    | CustomToolAction;

// Action Node Data
export interface ActionNodeData {
    name: string;
    description?: string;
    actions: ActionConfig[];
    execution_mode: 'sequential' | 'parallel';
    stop_on_error?: boolean;
    is_static?: boolean; // Static nodes are not supported
    // Inherited from FlowNodeData for compatibility
    invalid?: boolean;
    invalidField?: string | null;
    validationMessage?: string | null;
    selected_through_edge?: boolean;
    hovered_through_edge?: boolean;
}

// Default action node data
export const DEFAULT_ACTION_NODE_DATA: ActionNodeData = {
    name: 'Action',
    description: '',
    actions: [],
    execution_mode: 'sequential',
    stop_on_error: false,
    is_static: false, // Static nodes are not supported
};

// Call Variables Node Data — read-only post-call data hub. It holds no config
// of its own; the node aggregates every variable across the workflow live.
export interface CallVariablesNodeData {
    name: string;
    description?: string;
    is_static?: boolean;
    // Optional persisted snapshot of variables (the UI also aggregates live).
    extraction_variables?: ExtractionVariable[];
    invalid?: boolean;
    invalidField?: string | null;
    validationMessage?: string | null;
    selected_through_edge?: boolean;
    hovered_through_edge?: boolean;
}

export const DEFAULT_CALL_VARIABLES_DATA: CallVariablesNodeData = {
    name: 'Call Variables',
    description: 'Every variable collected during the call. Attach Action nodes here for post-call integrations.',
    is_static: false,
};

// =============================================================================
// Meeting Agent Node Types
// =============================================================================

export type MeetingTriggerMode = 'wake_word' | 'speaker_filter' | 'topic_detect' | 'always_listen';

export interface MeetingTriggerConfig {
    mode: MeetingTriggerMode;
    wake_words?: string[];
    speaker_filter?: string[];
    topic_keywords?: string[];
    cooldown_seconds?: number;
}

export interface MeetingTriggerNodeData {
    name: string;
    description?: string;
    trigger_config: MeetingTriggerConfig;
    response_prompt: string;
    knowledge_base?: KnowledgeBaseConfig;
    max_response_tokens?: number;
    invalid?: boolean;
    invalidField?: string | null;
    validationMessage?: string | null;
    selected_through_edge?: boolean;
    hovered_through_edge?: boolean;
}

export const DEFAULT_MEETING_TRIGGER_DATA: MeetingTriggerNodeData = {
    name: 'Wake Word Trigger',
    trigger_config: {
        mode: 'wake_word',
        wake_words: ['hey agent'],
        cooldown_seconds: 2,
    },
    response_prompt: 'Respond helpfully and concisely to the question based on the meeting context.',
    max_response_tokens: 300,
};

export type MeetingSummaryMode = 'periodic' | 'on_demand' | 'end_of_meeting';

export interface MeetingSummaryConfig {
    mode: MeetingSummaryMode;
    interval_minutes?: number;
    include_action_items: boolean;
    include_decisions: boolean;
    include_key_points: boolean;
}

export interface MeetingSummaryNodeData {
    name: string;
    description?: string;
    summary_config: MeetingSummaryConfig;
    output_format: 'text' | 'markdown' | 'json';
    invalid?: boolean;
    invalidField?: string | null;
    validationMessage?: string | null;
    selected_through_edge?: boolean;
    hovered_through_edge?: boolean;
}

export const DEFAULT_MEETING_SUMMARY_DATA: MeetingSummaryNodeData = {
    name: 'Meeting Summary',
    summary_config: {
        mode: 'end_of_meeting',
        include_action_items: true,
        include_decisions: true,
        include_key_points: true,
    },
    output_format: 'markdown',
};

// =============================================================================
// If/Else Node
// =============================================================================

export interface IfElseNodeData {
    name: string;
    condition_text: string;
    invalid?: boolean;
    invalidField?: string | null;
    validationMessage?: string | null;
    selected_through_edge?: boolean;
    hovered_through_edge?: boolean;
}

export const DEFAULT_IF_ELSE_DATA: IfElseNodeData = {
    name: 'If / Else',
    condition_text: '',
};

// =============================================================================
// Categorize Node
// =============================================================================

export interface CategorizeNodeData {
    name: string;
    prompt?: string;
    categories: string[];
    invalid?: boolean;
    invalidField?: string | null;
    validationMessage?: string | null;
    selected_through_edge?: boolean;
    hovered_through_edge?: boolean;
}

export const DEFAULT_CATEGORIZE_DATA: CategorizeNodeData = {
    name: 'Categorize',
    prompt: '',
    categories: ['Sales', 'Support'],
};

// =============================================================================
// Transfer Node
// =============================================================================

export interface TransferNodeData {
    name: string;
    prompt?: string;
    transfer_target?: string;
    is_literal?: boolean;
    invalid?: boolean;
    invalidField?: string | null;
    validationMessage?: string | null;
    selected_through_edge?: boolean;
    hovered_through_edge?: boolean;
}

export const DEFAULT_TRANSFER_DATA: TransferNodeData = {
    name: 'Transfer',
    prompt: 'Please hold while I transfer you.',
    transfer_target: '',
    is_literal: true,
};
