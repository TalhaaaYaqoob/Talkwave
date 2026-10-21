'use client';

import {
    AlertCircle,
    ArrowDown,
    ArrowUp,
    Check,
    ChevronDown,
    ChevronRight,
    ChevronUp,
    ExternalLink,
    GripVertical,
    MessageSquare,
    Plus,
    Power,
    Wrench,
    X,
    Zap,
} from 'lucide-react';

import { Spinner } from '@/components/ui/ai-loader';

import { getVisual } from '../common/integrationIcons';
import { findStaleActionRefs } from '../common/variableRefs';
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';

import {
    ActionConfig,
    ActionType,
    ApiCallAction,
    CustomToolAction,
    DatabaseQueryAction,
    GoogleSheetsAction,
    ScheduleMeetingAction,
    SendEmailAction,
    SendSlackAction,
    SendSmsAction,
    SendWhatsAppAction,
    SetVariableAction,
    WebhookAction,
} from '@/components/flow/types';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { getBackendUrl } from '@/lib/apiClient';
import { useAuth } from '@/lib/auth';
import { cn } from '@/lib/utils';

import { ApiCallActionPanel } from './ApiCallActionPanel';
import { DatabaseQueryActionPanel } from './DatabaseQueryActionPanel';
import { GoogleSheetsActionPanel } from './GoogleSheetsActionPanel';
import { ScheduleMeetingActionPanel } from './ScheduleMeetingActionPanel';
import { SendEmailActionPanel } from './SendEmailActionPanel';
import { SendSlackActionPanel } from './SendSlackActionPanel';
import { SendSmsActionPanel } from './SendSmsActionPanel';
import { SendWhatsAppActionPanel } from './SendWhatsAppActionPanel';
import { SetVariableActionPanel } from './SetVariableActionPanel';
import { VariableChips } from './VariableChips';
import { WebhookActionPanel } from './WebhookActionPanel';

interface ActionsListPanelProps {
    actions: ActionConfig[];
    setActions: (actions: ActionConfig[]) => void;
    executionMode: 'sequential' | 'parallel';
    setExecutionMode: (mode: 'sequential' | 'parallel') => void;
    availableVariables?: string[];
}

interface IntegrationStatus {
    integration_id: string;
    is_configured: boolean;
    is_enabled: boolean;
}

interface CustomToolFromLibrary {
    id: number;
    name: string;
    display_name: string | null;
    description: string;
    tool_type: string;
    is_active: boolean;
}

interface ActionTypeConfig {
    type: ActionType;
    name: string;
    description: string;
    icon: React.ReactNode;
    color: string;
    bgColor: string;
    requiredIntegration?: string;
    category: string;
}

interface ActionCategory {
    id: string;
    name: string;
    description: string;
    icon: React.ReactNode;
    color: string;
}

const ACTION_CATEGORIES: ActionCategory[] = [
    {
        id: 'messaging',
        name: 'Messaging',
        description: 'SMS, WhatsApp, Slack',
        icon: <MessageSquare className="w-4 h-4" />,
        color: 'text-emerald-500',
    },
    {
        id: 'email',
        name: 'Email',
        description: 'Gmail, SendGrid, SMTP',
        icon: getVisual('gmail').icon('w-4 h-4'),
        color: getVisual('gmail').color,
    },
    {
        id: 'productivity',
        name: 'Productivity',
        description: 'Sheets, Calendar, Notion, Drive',
        icon: getVisual('googlesheets').icon('w-4 h-4'),
        color: getVisual('googlesheets').color,
    },
    {
        id: 'crm',
        name: 'CRM & Business',
        description: 'HubSpot, GitHub, and more',
        icon: getVisual('hubspot').icon('w-4 h-4'),
        color: getVisual('hubspot').color,
    },
    {
        id: 'database',
        name: 'Database',
        description: 'PostgreSQL, MySQL, MongoDB',
        icon: getVisual('postgresql').icon('w-4 h-4'),
        color: getVisual('postgresql').color,
    },
    {
        id: 'api',
        name: 'API & Webhooks',
        description: 'HTTP requests and webhooks',
        icon: getVisual('http_api').icon('w-4 h-4'),
        color: getVisual('http_api').color,
    },
    {
        id: 'utility',
        name: 'Utility',
        description: 'Variables and internal operations',
        icon: getVisual('set_variable').icon('w-4 h-4'),
        color: getVisual('set_variable').color,
    },
];

const ACTION_TYPES: ActionTypeConfig[] = [
    // Messaging
    { type: 'send_sms', name: 'Twilio SMS', description: 'Send SMS via Twilio',
      icon: getVisual('twilio').icon(), color: getVisual('twilio').color, bgColor: getVisual('twilio').bgColor, requiredIntegration: 'twilio', category: 'messaging' },
    { type: 'send_whatsapp', name: 'WhatsApp', description: 'Send WhatsApp message',
      icon: getVisual('whatsapp').icon(), color: getVisual('whatsapp').color, bgColor: getVisual('whatsapp').bgColor, requiredIntegration: 'whatsapp', category: 'messaging' },
    { type: 'send_slack', name: 'Slack', description: 'Post to Slack channel',
      icon: getVisual('slack').icon(), color: getVisual('slack').color, bgColor: getVisual('slack').bgColor, requiredIntegration: 'slack', category: 'messaging' },
    // Email
    { type: 'send_email', name: 'Gmail', description: 'Send email via Gmail',
      icon: getVisual('gmail').icon(), color: getVisual('gmail').color, bgColor: getVisual('gmail').bgColor, requiredIntegration: 'gmail', category: 'email' },
    { type: 'send_email', name: 'SendGrid', description: 'Email via SendGrid',
      icon: getVisual('sendgrid').icon(), color: getVisual('sendgrid').color, bgColor: getVisual('sendgrid').bgColor, requiredIntegration: 'sendgrid', category: 'email' },
    { type: 'send_email', name: 'SMTP Email', description: 'Email via SMTP',
      icon: getVisual('smtp').icon(), color: getVisual('smtp').color, bgColor: getVisual('smtp').bgColor, requiredIntegration: 'smtp', category: 'email' },
    { type: 'send_email', name: 'Mailgun', description: 'Email via Mailgun',
      icon: getVisual('mailgun').icon(), color: getVisual('mailgun').color, bgColor: getVisual('mailgun').bgColor, requiredIntegration: 'mailgun', category: 'email' },
    // Productivity
    { type: 'google_sheets', name: 'Google Sheets', description: 'Read/write spreadsheets',
      icon: getVisual('googlesheets').icon(), color: getVisual('googlesheets').color, bgColor: getVisual('googlesheets').bgColor, requiredIntegration: 'googlesheets', category: 'productivity' },
    { type: 'schedule_meeting', name: 'Google Calendar', description: 'Schedule meetings & events',
      icon: getVisual('googlecalendar').icon(), color: getVisual('googlecalendar').color, bgColor: getVisual('googlecalendar').bgColor, requiredIntegration: 'googlecalendar', category: 'productivity' },
    { type: 'api_call', name: 'Notion', description: 'Manage Notion pages',
      icon: getVisual('notion').icon(), color: getVisual('notion').color, bgColor: getVisual('notion').bgColor, requiredIntegration: 'notion', category: 'productivity' },
    { type: 'api_call', name: 'Airtable', description: 'Manage Airtable records',
      icon: getVisual('airtable').icon(), color: getVisual('airtable').color, bgColor: getVisual('airtable').bgColor, requiredIntegration: 'airtable', category: 'productivity' },
    { type: 'api_call', name: 'Google Drive', description: 'Upload & manage files',
      icon: getVisual('googledrive').icon(), color: getVisual('googledrive').color, bgColor: getVisual('googledrive').bgColor, requiredIntegration: 'googledrive', category: 'productivity' },
    // CRM & Business
    { type: 'api_call', name: 'HubSpot', description: 'CRM & contacts',
      icon: getVisual('hubspot').icon(), color: getVisual('hubspot').color, bgColor: getVisual('hubspot').bgColor, requiredIntegration: 'hubspot', category: 'crm' },
    { type: 'api_call', name: 'GitHub', description: 'Manage repos & issues',
      icon: getVisual('github').icon(), color: getVisual('github').color, bgColor: getVisual('github').bgColor, requiredIntegration: 'github', category: 'crm' },
    // Database
    { type: 'database_query', name: 'PostgreSQL', description: 'Query PostgreSQL database',
      icon: getVisual('postgresql').icon(), color: getVisual('postgresql').color, bgColor: getVisual('postgresql').bgColor, requiredIntegration: 'postgresql', category: 'database' },
    { type: 'database_query', name: 'MySQL', description: 'Query MySQL database',
      icon: getVisual('mysql').icon(), color: getVisual('mysql').color, bgColor: getVisual('mysql').bgColor, requiredIntegration: 'mysql', category: 'database' },
    { type: 'database_query', name: 'MongoDB', description: 'Query MongoDB database',
      icon: getVisual('mongodb').icon(), color: getVisual('mongodb').color, bgColor: getVisual('mongodb').bgColor, requiredIntegration: 'mongodb', category: 'database' },
    { type: 'database_query', name: 'Supabase', description: 'Supabase operations',
      icon: getVisual('supabase').icon(), color: getVisual('supabase').color, bgColor: getVisual('supabase').bgColor, requiredIntegration: 'supabase', category: 'database' },
    { type: 'database_query', name: 'Firebase', description: 'Firebase/Firestore operations',
      icon: getVisual('firebase').icon(), color: getVisual('firebase').color, bgColor: getVisual('firebase').bgColor, requiredIntegration: 'firebase', category: 'database' },
    // API & Webhooks
    { type: 'webhook', name: 'Webhook', description: 'Send data to webhook',
      icon: getVisual('webhook').icon(), color: getVisual('webhook').color, bgColor: getVisual('webhook').bgColor, category: 'api' },
    { type: 'api_call', name: 'HTTP API', description: 'Make HTTP API request',
      icon: getVisual('http_api').icon(), color: getVisual('http_api').color, bgColor: getVisual('http_api').bgColor, category: 'api' },
    // Utility
    { type: 'set_variable', name: 'Set Variable', description: 'Set or update variable',
      icon: getVisual('set_variable').icon(), color: getVisual('set_variable').color, bgColor: getVisual('set_variable').bgColor, category: 'utility' },
];

const createDefaultAction = (type: ActionType, serviceName?: string): ActionConfig => {
    const id = `action-${Date.now()}`;
    const base = { id, enabled: true, continue_on_error: false };

    switch (type) {
        case 'send_sms':
            return { ...base, type: 'send_sms', name: serviceName || 'Send SMS', to_number: '', message: '' } as SendSmsAction;
        case 'send_email':
            return { ...base, type: 'send_email', name: serviceName || 'Send Email', to_email: '', subject: '', body: '', is_html: false } as SendEmailAction;
        case 'send_whatsapp':
            return { ...base, type: 'send_whatsapp', name: serviceName || 'Send WhatsApp', to_number: '', message: '' } as SendWhatsAppAction;
        case 'send_slack':
            return { ...base, type: 'send_slack', name: serviceName || 'Send Slack', channel: '', message: '' } as SendSlackAction;
        case 'database_query': {
            const dbServiceMap: Record<string, string> = {
                'PostgreSQL': 'postgresql', 'MySQL': 'mysql', 'MongoDB': 'mongodb',
                'Supabase': 'supabase', 'Firebase': 'firebase',
            };
            const dbService = serviceName ? (dbServiceMap[serviceName] || serviceName.toLowerCase()) : '';
            return { ...base, type: 'database_query', name: serviceName || 'Database Query', database_service: dbService, operation: 'query', query_template: '', table_name: '', description: '' } as DatabaseQueryAction;
        }
        case 'google_sheets':
            return { ...base, type: 'google_sheets', name: 'Update Sheet', operation: 'append', spreadsheet_id: '', sheet_name: 'Sheet1', data_mapping: {} } as GoogleSheetsAction;
        case 'schedule_meeting':
            return { ...base, type: 'schedule_meeting', name: serviceName || 'Schedule Meeting', event_title: '', attendee_email: '', start_time: '', end_time: '', timezone: 'UTC', send_notifications: true } as ScheduleMeetingAction;
        case 'webhook':
            return { ...base, type: 'webhook', name: serviceName || 'Send Webhook', url: '', method: 'POST', body_template: '', headers: {}, timeout_seconds: 30 } as WebhookAction;
        case 'api_call':
            return { ...base, type: 'api_call', name: serviceName || 'API Call', url: '', method: 'GET', body_template: '', headers: {}, timeout_seconds: 30 } as ApiCallAction;
        case 'set_variable':
            return { ...base, type: 'set_variable', name: 'Set Variable', variable_name: '', value: '', value_type: 'string' } as SetVariableAction;
        case 'custom_tool':
            return { ...base, type: 'custom_tool', name: serviceName || 'Custom Tool', tool_id: 0, tool_name: '' } as CustomToolAction;
        default:
            return { ...base, type: 'webhook', name: serviceName || 'Action', url: '', method: 'POST', timeout_seconds: 30 } as WebhookAction;
    }
};

const getActionTypeConfig = (type: ActionType) => ACTION_TYPES.find(t => t.type === type);

const ACTION_TYPE_TO_VISUAL: Record<string, string> = {
    send_sms: 'twilio',
    send_email: 'gmail',
    send_whatsapp: 'whatsapp',
    send_slack: 'slack',
    google_sheets: 'googlesheets',
    schedule_meeting: 'googlecalendar',
    webhook: 'webhook',
    api_call: 'http_api',
    set_variable: 'set_variable',
    database_query: 'postgresql',
    custom_tool: 'custom_tool',
};

const getActionIcon = (type: ActionType): React.ReactNode => {
    return getVisual(ACTION_TYPE_TO_VISUAL[type] || type).icon('w-4 h-4');
};

const getActionColor = (type: ActionType): string => {
    return getVisual(ACTION_TYPE_TO_VISUAL[type] || type).color;
};

const getActionBgColor = (type: ActionType): string => {
    const bg = getVisual(ACTION_TYPE_TO_VISUAL[type] || type).bgColor;
    return bg.replace(/hover:\S+/g, '').trim();
};

// Custom Tool Config Panel (inline for action node)
function CustomToolConfigPanel({
    action,
    onChange,
    availableVariables = [],
}: {
    action: CustomToolAction;
    onChange: (a: CustomToolAction) => void;
    availableVariables?: string[];
}) {
    const inputData = action.input_data || {};
    const [newKey, setNewKey] = useState('');

    const addParam = () => {
        if (!newKey.trim()) return;
        onChange({ ...action, input_data: { ...inputData, [newKey.trim()]: '' } });
        setNewKey('');
    };

    const removeParam = (key: string) => {
        const updated = { ...inputData };
        delete updated[key];
        onChange({ ...action, input_data: updated });
    };

    return (
        <div className="space-y-4">
            <div className="space-y-2">
                <Label>Action Name</Label>
                <Input
                    value={action.name}
                    onChange={(e) => onChange({ ...action, name: e.target.value })}
                    placeholder="e.g., Run Custom Tool"
                />
            </div>

            <div className="space-y-2">
                <Label>Input Parameters</Label>
                <p className="text-xs text-muted-foreground">
                    Pass extracted variables to the tool. Use {'{{variable_name}}'} syntax.
                </p>
                {Object.entries(inputData).map(([key, value]) => (
                    <div key={key} className="flex gap-2 items-center">
                        <Input value={key} disabled className="w-1/3 text-xs" />
                        <Input
                            value={value}
                            onChange={(e) => onChange({ ...action, input_data: { ...inputData, [key]: e.target.value } })}
                            placeholder={`{{${availableVariables[0] || 'variable'}}}`}
                            className="flex-1 text-xs"
                        />
                        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => removeParam(key)}>
                            <X className="w-3 h-3" />
                        </Button>
                    </div>
                ))}
                <div className="flex gap-2">
                    <Input
                        value={newKey}
                        onChange={(e) => setNewKey(e.target.value)}
                        placeholder="Parameter name"
                        className="text-xs"
                        onKeyDown={(e) => e.key === 'Enter' && addParam()}
                    />
                    <Button variant="outline" size="sm" onClick={addParam} disabled={!newKey.trim()}>
                        <Plus className="w-3 h-3 mr-1" /> Add
                    </Button>
                </div>
            </div>

            <VariableChips variables={availableVariables} className="space-y-2" />

            <div className="flex items-center gap-2 mt-2">
                <input
                    type="checkbox"
                    id="continue-on-error"
                    checked={action.continue_on_error || false}
                    onChange={(e) => onChange({ ...action, continue_on_error: e.target.checked })}
                    className="rounded"
                />
                <Label htmlFor="continue-on-error" className="text-sm cursor-pointer">
                    Continue on error
                </Label>
            </div>
        </div>
    );
}

export function ActionsListPanel({
    actions,
    setActions,
    executionMode,
    setExecutionMode,
    availableVariables = [],
}: ActionsListPanelProps) {
    const { getAccessToken } = useAuth();
    const [expandedActions, setExpandedActions] = useState<Set<string>>(new Set());
    const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set(['messaging', 'productivity', 'api', 'utility']));
    const [configDialogOpen, setConfigDialogOpen] = useState(false);
    const [editingAction, setEditingAction] = useState<ActionConfig | null>(null);
    const [selectedActionType, setSelectedActionType] = useState<ActionType | null>(null);

    // Integration status (Composio is the source of truth)
    const [integrationStatuses, setIntegrationStatuses] = useState<IntegrationStatus[]>([]);
    const [isLoadingStatuses, setIsLoadingStatuses] = useState(true);

    // Custom tools from library
    const [customToolsLibrary, setCustomToolsLibrary] = useState<CustomToolFromLibrary[]>([]);
    const [isLoadingCustomTools, setIsLoadingCustomTools] = useState(true);

    // Stale {{variable}} references — placeholders used by actions that no node
    // in the workflow produces. They render empty at runtime, so warn here.
    const staleRefs = useMemo(
        () => findStaleActionRefs(actions, availableVariables),
        [actions, availableVariables],
    );

    // Fetch all statuses on mount (Composio is the source of truth)
    useEffect(() => {
        const fetchAll = async () => {
            try {
                const accessToken = await getAccessToken();
                const headers = { 'Authorization': `Bearer ${accessToken}` };

                const base = getBackendUrl();
                const [composioRes, toolsRes] = await Promise.allSettled([
                    fetch(`${base}/api/v1/composio/apps`, { headers }),
                    fetch(`${base}/api/v1/custom-tools/`, { headers }),
                ]);

                const statuses: IntegrationStatus[] = [];
                if (composioRes.status === 'fulfilled' && composioRes.value.ok) {
                    const apps = await composioRes.value.json();
                    for (const app of apps) {
                        statuses.push({
                            integration_id: app.id,
                            is_configured: app.is_connected || app.status === 'ACTIVE',
                            is_enabled: app.is_connected || app.status === 'ACTIVE',
                        });
                    }
                }
                setIntegrationStatuses(statuses);

                if (toolsRes.status === 'fulfilled' && toolsRes.value.ok) {
                    const data = await toolsRes.value.json();
                    setCustomToolsLibrary(
                        (data.tools || data || []).filter((t: CustomToolFromLibrary) => t.is_active)
                    );
                }
            } catch (err) {
                console.error('Failed to fetch statuses:', err);
            } finally {
                setIsLoadingStatuses(false);
                setIsLoadingCustomTools(false);
            }
        };
        fetchAll();
    }, [getAccessToken]);

    const isIntegrationConfigured = (integrationId?: string): boolean => {
        if (!integrationId) return true;
        return integrationStatuses.some(s => s.integration_id === integrationId && s.is_configured && s.is_enabled);
    };

    const isActionTypeAvailable = (actionType: ActionTypeConfig): boolean => {
        if (actionType.requiredIntegration) return isIntegrationConfigured(actionType.requiredIntegration);
        return true;
    };

    const toggleExpand = (actionId: string) => {
        const newExpanded = new Set(expandedActions);
        if (newExpanded.has(actionId)) newExpanded.delete(actionId);
        else newExpanded.add(actionId);
        setExpandedActions(newExpanded);
    };

    const toggleCategory = (categoryId: string) => {
        const newExpanded = new Set(expandedCategories);
        if (newExpanded.has(categoryId)) newExpanded.delete(categoryId);
        else newExpanded.add(categoryId);
        setExpandedCategories(newExpanded);
    };

    const handleAddAction = (actionConfig: ActionTypeConfig) => {
        const newAction = createDefaultAction(actionConfig.type, actionConfig.name);
        setEditingAction(newAction);
        setSelectedActionType(actionConfig.type);
        setConfigDialogOpen(true);
    };

    const handleAddCustomToolAction = (ct: CustomToolFromLibrary) => {
        const newAction: CustomToolAction = {
            id: `action-${Date.now()}`,
            type: 'custom_tool',
            name: ct.display_name || ct.name,
            enabled: true,
            continue_on_error: false,
            tool_id: ct.id,
            tool_name: ct.name,
            input_data: {},
        };
        setEditingAction(newAction);
        setSelectedActionType('custom_tool');
        setConfigDialogOpen(true);
    };

    const handleEditAction = (action: ActionConfig) => {
        setEditingAction({ ...action });
        setSelectedActionType(action.type);
        setConfigDialogOpen(true);
    };

    const handleSaveAction = () => {
        if (!editingAction) return;
        const existingIndex = actions.findIndex(a => a.id === editingAction.id);
        if (existingIndex >= 0) {
            const newActions = [...actions];
            newActions[existingIndex] = editingAction;
            setActions(newActions);
        } else {
            setActions([...actions, editingAction]);
        }
        setConfigDialogOpen(false);
        setEditingAction(null);
        setSelectedActionType(null);
    };

    const handleDeleteAction = (actionId: string) => {
        setActions(actions.filter(a => a.id !== actionId));
    };

    const handleToggleAction = (actionId: string) => {
        setActions(actions.map(a => a.id === actionId ? { ...a, enabled: !a.enabled } : a));
    };

    const handleMoveAction = (actionId: string, direction: 'up' | 'down') => {
        const index = actions.findIndex(a => a.id === actionId);
        if (index < 0) return;
        const newIndex = direction === 'up' ? index - 1 : index + 1;
        if (newIndex < 0 || newIndex >= actions.length) return;
        const newActions = [...actions];
        [newActions[index], newActions[newIndex]] = [newActions[newIndex], newActions[index]];
        setActions(newActions);
    };

    const getActionsForCategory = (categoryId: string) => {
        return ACTION_TYPES.filter(a => a.category === categoryId);
    };

    const renderActionConfig = () => {
        if (!editingAction || !selectedActionType) return null;

        switch (selectedActionType) {
            case 'send_sms':
                return <SendSmsActionPanel action={editingAction as SendSmsAction} onChange={(a) => setEditingAction(a)} availableVariables={availableVariables} />;
            case 'send_email':
                return <SendEmailActionPanel action={editingAction as SendEmailAction} onChange={(a) => setEditingAction(a)} availableVariables={availableVariables} />;
            case 'send_whatsapp':
                return <SendWhatsAppActionPanel action={editingAction as SendWhatsAppAction} onChange={(a) => setEditingAction(a)} availableVariables={availableVariables} />;
            case 'send_slack':
                return <SendSlackActionPanel action={editingAction as SendSlackAction} onChange={(a) => setEditingAction(a)} availableVariables={availableVariables} />;
            case 'database_query':
                return <DatabaseQueryActionPanel action={editingAction as DatabaseQueryAction} onChange={(a) => setEditingAction(a)} availableVariables={availableVariables} />;
            case 'google_sheets':
                return <GoogleSheetsActionPanel action={editingAction as GoogleSheetsAction} onChange={(a) => setEditingAction(a)} availableVariables={availableVariables} />;
            case 'schedule_meeting':
                return <ScheduleMeetingActionPanel action={editingAction as ScheduleMeetingAction} onChange={(a) => setEditingAction(a)} availableVariables={availableVariables} />;
            case 'webhook':
                return <WebhookActionPanel action={editingAction as WebhookAction} onChange={(a) => setEditingAction(a)} availableVariables={availableVariables} />;
            case 'api_call':
                return <ApiCallActionPanel action={editingAction as ApiCallAction} onChange={(a) => setEditingAction(a)} availableVariables={availableVariables} />;
            case 'set_variable':
                return <SetVariableActionPanel action={editingAction as SetVariableAction} onChange={(a) => setEditingAction(a)} availableVariables={availableVariables} />;
            case 'custom_tool':
                return <CustomToolConfigPanel action={editingAction as CustomToolAction} onChange={(a) => setEditingAction(a)} availableVariables={availableVariables} />;
            default:
                return null;
        }
    };

    return (
        <div className="space-y-6 max-h-[60vh] overflow-y-auto pr-2">
            {/* Execution Mode */}
            <div className="space-y-3">
                <Label className="text-sm font-medium">Execution Mode</Label>
                <div className="grid grid-cols-2 gap-2">
                    <button
                        type="button"
                        onClick={() => setExecutionMode('sequential')}
                        className={cn(
                            "p-3 rounded-lg border text-left transition-all",
                            executionMode === 'sequential'
                                ? 'border-primary/50 bg-primary/10 ring-1 ring-primary/30'
                                : 'border-border/50 bg-card/50 hover:bg-muted/50'
                        )}
                    >
                        <div className="flex items-center gap-2 mb-1">
                            <ArrowDown className={cn("w-4 h-4", executionMode === 'sequential' ? 'text-primary' : 'text-muted-foreground')} />
                            <span className="font-medium text-sm">Sequential</span>
                        </div>
                        <p className="text-xs text-muted-foreground">Run actions one after another</p>
                    </button>
                    <button
                        type="button"
                        onClick={() => setExecutionMode('parallel')}
                        className={cn(
                            "p-3 rounded-lg border text-left transition-all",
                            executionMode === 'parallel'
                                ? 'border-primary/50 bg-primary/10 ring-1 ring-primary/30'
                                : 'border-border/50 bg-card/50 hover:bg-muted/50'
                        )}
                    >
                        <div className="flex items-center gap-2 mb-1">
                            <div className={cn("w-4 h-4 flex", executionMode === 'parallel' ? 'text-primary' : 'text-muted-foreground')}>
                                <ArrowDown className="w-2 h-4" />
                                <ArrowDown className="w-2 h-4" />
                            </div>
                            <span className="font-medium text-sm">Parallel</span>
                        </div>
                        <p className="text-xs text-muted-foreground">Run all actions at once</p>
                    </button>
                </div>
            </div>

            {/* Stale variable references warning */}
            {staleRefs.all.length > 0 && (
                <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
                    <div className="flex items-start gap-2">
                        <AlertCircle className="w-4 h-4 text-amber-500 mt-0.5 flex-shrink-0" />
                        <div className="flex-1">
                            <p className="text-sm text-amber-600 dark:text-amber-400">
                                {staleRefs.all.length} variable{staleRefs.all.length > 1 ? 's are' : ' is'} referenced but never collected
                            </p>
                            <p className="text-xs text-muted-foreground mt-1">
                                These render empty at runtime. Remove them, fix the spelling, or
                                collect them on an agent node:
                            </p>
                            <div className="flex flex-wrap gap-1 mt-2">
                                {staleRefs.all.map((v) => (
                                    <Badge key={v} variant="outline" className="text-xs font-mono border-amber-500/40 text-amber-600 dark:text-amber-400">
                                        {`{{${v}}}`}
                                    </Badge>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Configured Actions List */}
            <div className="space-y-3">
                <div className="flex items-center justify-between">
                    <Label className="text-sm font-medium">Actions ({actions.length})</Label>
                </div>

                {actions.length > 0 ? (
                    <div className="space-y-2">
                        {actions.map((action, index) => {
                            const isExpanded = expandedActions.has(action.id);
                            const actionName = action.name || action.type;

                            return (
                                <div
                                    key={action.id}
                                    className={cn(
                                        "border rounded-lg overflow-hidden transition-all",
                                        action.enabled ? 'bg-card/50' : 'bg-muted/20 opacity-60'
                                    )}
                                >
                                    <div className="flex items-center gap-2 p-3">
                                        <div className="flex flex-col items-center gap-0.5">
                                            <Button variant="ghost" size="icon" className="h-5 w-5"
                                                onClick={() => handleMoveAction(action.id, 'up')} disabled={index === 0}>
                                                <ArrowUp className="w-3 h-3" />
                                            </Button>
                                            <GripVertical className="w-4 h-4 text-muted-foreground" />
                                            <Button variant="ghost" size="icon" className="h-5 w-5"
                                                onClick={() => handleMoveAction(action.id, 'down')} disabled={index === actions.length - 1}>
                                                <ArrowDown className="w-3 h-3" />
                                            </Button>
                                        </div>

                                        <div className={cn("p-2 rounded-md border", getActionBgColor(action.type))}>
                                            <span className={getActionColor(action.type)}>{getActionIcon(action.type)}</span>
                                        </div>

                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2">
                                                <span className="font-medium text-sm truncate">{actionName}</span>
                                                <Badge variant="outline" className="text-xs">
                                                    {action.type === 'custom_tool' ? 'custom' : action.type.replace(/_/g, ' ')}
                                                </Badge>
                                                {staleRefs.byAction[action.id]?.length > 0 && (
                                                    <Badge
                                                        variant="outline"
                                                        className="text-xs border-amber-500/40 text-amber-500 bg-amber-500/10"
                                                        title={`Unknown variable(s): ${staleRefs.byAction[action.id].map(v => `{{${v}}}`).join(', ')}`}
                                                    >
                                                        <AlertCircle className="w-3 h-3 mr-1" />
                                                        {staleRefs.byAction[action.id].length}
                                                    </Badge>
                                                )}
                                            </div>
                                        </div>

                                        <div className="flex items-center gap-1">
                                            <Button variant="ghost" size="icon" className="h-7 w-7"
                                                onClick={() => handleToggleAction(action.id)}>
                                                <Power className={cn("w-3.5 h-3.5", action.enabled ? 'text-green-500' : 'text-muted-foreground')} />
                                            </Button>
                                            <Button variant="ghost" size="icon" className="h-7 w-7"
                                                onClick={() => toggleExpand(action.id)}>
                                                {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                                            </Button>
                                            <Button variant="ghost" size="icon" className="h-7 w-7"
                                                onClick={() => handleEditAction(action)}>
                                                <Wrench className="w-3.5 h-3.5" />
                                            </Button>
                                            <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive"
                                                onClick={() => handleDeleteAction(action.id)}>
                                                <X className="w-4 h-4" />
                                            </Button>
                                        </div>
                                    </div>

                                    {isExpanded && (
                                        <div className="border-t bg-muted/20 p-3 text-xs space-y-1">
                                            <p className="text-muted-foreground">
                                                Type: <span className="text-foreground">{action.type.replace(/_/g, ' ')}</span>
                                            </p>
                                            {action.continue_on_error && (
                                                <p className="text-muted-foreground">
                                                    Continue on error: <span className="text-green-500">Yes</span>
                                                </p>
                                            )}
                                            {action.type === 'custom_tool' && (
                                                <p className="text-muted-foreground">
                                                    Tool: <span className="text-foreground">{(action as CustomToolAction).tool_name}</span>
                                                </p>
                                            )}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                ) : (
                    <div className="border border-dashed rounded-lg p-6 text-center bg-muted/5">
                        <Plus className="w-8 h-8 text-muted-foreground mx-auto mb-2 opacity-50" />
                        <p className="text-sm text-muted-foreground">No actions configured</p>
                        <p className="text-xs text-muted-foreground">Add actions to execute after the conversation</p>
                    </div>
                )}
            </div>

            {/* Add Action - Categorized */}
            <div className="space-y-3">
                <div className="flex items-center justify-between">
                    <Label className="text-sm font-medium">Add Action</Label>
                    {isLoadingStatuses && <Spinner size="sm" />}
                </div>

                <div className="space-y-2">
                    {ACTION_CATEGORIES.map((category) => {
                        const categoryActions = getActionsForCategory(category.id);
                        if (categoryActions.length === 0) return null;
                        const isExpanded = expandedCategories.has(category.id);
                        const availableCount = categoryActions.filter(a => isActionTypeAvailable(a)).length;

                        return (
                            <Collapsible key={category.id} open={isExpanded} onOpenChange={() => toggleCategory(category.id)}>
                                <CollapsibleTrigger asChild>
                                    <button className="w-full flex items-center justify-between p-3 rounded-lg border bg-card/50 hover:bg-muted/50 transition-colors">
                                        <div className="flex items-center gap-3">
                                            <span className={category.color}>{category.icon}</span>
                                            <div className="text-left">
                                                <p className="font-medium text-sm">{category.name}</p>
                                                <p className="text-xs text-muted-foreground">{category.description}</p>
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <Badge variant="outline" className="text-xs">
                                                {availableCount}/{categoryActions.length}
                                            </Badge>
                                            {isExpanded ? <ChevronDown className="w-4 h-4 text-muted-foreground" /> : <ChevronRight className="w-4 h-4 text-muted-foreground" />}
                                        </div>
                                    </button>
                                </CollapsibleTrigger>
                                <CollapsibleContent>
                                    <div className="grid grid-cols-2 gap-2 pt-2 pl-2">
                                        {categoryActions.map((actionType, idx) => {
                                            const isAvailable = isActionTypeAvailable(actionType);
                                            const needsConfig = actionType.requiredIntegration && !isAvailable;

                                            return (
                                                <div key={`${actionType.type}-${idx}`} className="relative">
                                                    <button
                                                        onClick={() => isAvailable && handleAddAction(actionType)}
                                                        disabled={!isAvailable}
                                                        className={cn(
                                                            "w-full p-3 rounded-lg border text-left transition-all",
                                                            isAvailable
                                                                ? actionType.bgColor
                                                                : 'bg-muted/20 border-muted/30 opacity-60 cursor-not-allowed'
                                                        )}
                                                    >
                                                        <span className={isAvailable ? actionType.color : 'text-muted-foreground'}>
                                                            {actionType.icon}
                                                        </span>
                                                        <p className={cn("text-sm font-medium mt-1", !isAvailable && 'text-muted-foreground')}>
                                                            {actionType.name}
                                                        </p>
                                                        <p className="text-xs text-muted-foreground mt-0.5">{actionType.description}</p>
                                                        {needsConfig && (
                                                            <div className="flex items-center gap-1 mt-1">
                                                                <AlertCircle className="w-3 h-3 text-amber-500" />
                                                                <span className="text-xs text-amber-500">Not configured</span>
                                                            </div>
                                                        )}
                                                    </button>
                                                    {needsConfig && (
                                                        <Link
                                                            href="/integrations"
                                                            className="absolute inset-0 flex items-end justify-center pb-2 opacity-0 hover:opacity-100 transition-opacity"
                                                        >
                                                            <span className="bg-primary text-primary-foreground text-xs px-2 py-1 rounded-full flex items-center gap-1">
                                                                Configure <ExternalLink className="w-3 h-3" />
                                                            </span>
                                                        </Link>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                </CollapsibleContent>
                            </Collapsible>
                        );
                    })}
                </div>
            </div>

            {/* Custom Tools from Library */}
            {!isLoadingCustomTools && customToolsLibrary.length > 0 && (
                <div className="space-y-3">
                    <div className="flex items-center justify-between">
                        <Label className="text-sm font-medium flex items-center gap-2">
                            <Wrench className="w-4 h-4 text-primary" />
                            Custom Tools Library
                        </Label>
                        <Link href="/custom-tools" className="text-xs text-primary hover:underline inline-flex items-center gap-1">
                            Manage <ExternalLink className="w-3 h-3" />
                        </Link>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                        {customToolsLibrary.map((ct) => {
                            const isAdded = actions.some(a => a.type === 'custom_tool' && (a as CustomToolAction).tool_id === ct.id);
                            return (
                                <button
                                    key={ct.id}
                                    onClick={() => !isAdded && handleAddCustomToolAction(ct)}
                                    disabled={isAdded}
                                    className={cn(
                                        "w-full p-3 rounded-lg border text-left transition-all",
                                        isAdded
                                            ? "bg-primary/10 border-primary/20 ring-1 ring-offset-1 ring-offset-background opacity-70"
                                            : "bg-primary/10 hover:bg-primary/20 border-primary/20"
                                    )}
                                >
                                    <div className="flex items-center gap-2 mb-1">
                                        <span className="text-primary"><Wrench className="w-4 h-4" /></span>
                                        <Badge variant="outline" className="text-[10px] px-1 py-0">{ct.tool_type}</Badge>
                                        {isAdded && <Check className="w-3 h-3 text-green-500 ml-auto" />}
                                    </div>
                                    <p className="text-sm font-medium">{ct.display_name || ct.name}</p>
                                    <p className="text-xs text-muted-foreground line-clamp-2">{ct.description}</p>
                                </button>
                            );
                        })}
                    </div>
                </div>
            )}
            {!isLoadingCustomTools && customToolsLibrary.length === 0 && (
                <div className="p-3 rounded-lg bg-muted/10 border border-dashed">
                    <div className="flex items-center gap-2">
                        <Wrench className="w-4 h-4 text-muted-foreground" />
                        <div className="flex-1">
                            <p className="text-xs text-muted-foreground">
                                No custom tools yet.{' '}
                                <Link href="/custom-tools" className="text-primary hover:underline">Create one</Link>
                            </p>
                        </div>
                    </div>
                </div>
            )}

            {/* Configuration Notice */}
            {!isLoadingStatuses && integrationStatuses.some(s => !s.is_configured) && (
                <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
                    <div className="flex items-start gap-2">
                        <AlertCircle className="w-4 h-4 text-amber-500 mt-0.5 flex-shrink-0" />
                        <div className="flex-1">
                            <p className="text-sm text-amber-600 dark:text-amber-400">
                                Some integrations need to be connected
                            </p>
                            <p className="text-xs text-muted-foreground mt-1">
                                Go to{' '}
                                <Link href="/integrations" className="text-primary hover:underline inline-flex items-center gap-1">
                                    Integrations <ExternalLink className="w-3 h-3" />
                                </Link>
                                {' '}to connect your apps.
                            </p>
                        </div>
                    </div>
                </div>
            )}

            {/* Available Variables */}
            <VariableChips
                variables={availableVariables}
                label="Available Variables (from extraction)"
                className="space-y-2"
            />

            {/* Configuration Dialog */}
            <Dialog open={configDialogOpen} onOpenChange={setConfigDialogOpen}>
                <DialogContent className="max-w-2xl max-h-[85vh] overflow-hidden flex flex-col">
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-3">
                            {selectedActionType && (
                                <span className={getActionColor(selectedActionType)}>
                                    {getActionIcon(selectedActionType)}
                                </span>
                            )}
                            {editingAction && actions.find(a => a.id === editingAction.id) ? 'Edit Action' : 'Add Action'}
                        </DialogTitle>
                        <DialogDescription>
                            Configure the action parameters and execution settings
                        </DialogDescription>
                    </DialogHeader>

                    <div className="flex-1 overflow-y-auto pr-2 py-4">
                        {renderActionConfig()}
                    </div>

                    <DialogFooter className="border-t pt-4">
                        <Button variant="outline" onClick={() => setConfigDialogOpen(false)}>Cancel</Button>
                        <Button onClick={handleSaveAction}>
                            <Check className="w-4 h-4 mr-2" />
                            {editingAction && actions.find(a => a.id === editingAction.id) ? 'Update Action' : 'Add Action'}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
