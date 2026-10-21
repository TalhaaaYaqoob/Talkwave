'use client';

import {
    AlertCircle,
    Check,
    Code2,
    ExternalLink,
    Globe,
    Plug,
    Plus,
    Wrench,
    X,
    Zap,
} from 'lucide-react';
import Link from 'next/link';
import { useEffect, useState } from 'react';

import {
    AgentToolReference,
    ApiToolConfig,
    EmailConfig,
    FunctionConfig,
    GoogleCalendarConfig,
    GoogleSheetsConfig,
    IntegrationToolType,
    McpServerConfig,
    TwilioSmsConfig,
} from '@/components/flow/types';
import { Button } from '@/components/ui/button';
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
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { getBackendUrl } from '@/lib/apiClient';
import { useAuth } from '@/lib/auth';
import { cn } from '@/lib/utils';

import {
    ApiToolConfig as ApiToolConfigComponent,
    DEFAULT_API_CONFIG,
    DEFAULT_EMAIL_CONFIG,
    DEFAULT_FUNCTION_CONFIG,
    DEFAULT_GOOGLE_CALENDAR_CONFIG,
    DEFAULT_GOOGLE_SHEETS_CONFIG,
    DEFAULT_MCP_SERVER_CONFIG,
    DEFAULT_TWILIO_SMS_CONFIG,
    EmailToolConfig,
    FunctionToolConfig,
    GoogleCalendarToolConfig,
    GoogleSheetsToolConfig,
    McpServerToolConfig,
    TwilioSmsToolConfig,
} from './tools';

import { getVisual } from '../common/integrationIcons';

interface ToolsPanelProps {
    tools: AgentToolReference[];
    setTools: (tools: AgentToolReference[]) => void;
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

// A connected app pulled live from the Integrations tab (/composio/apps).
interface ConnectedApp {
    id: string;
    name: string;
    description: string;
    category: string;
    logo?: string;
    color: string;
}

// =============================================================================
// Integration Definitions - 6 Essential Tools
// =============================================================================

interface IntegrationToolDef {
    id: string;
    type: IntegrationToolType;
    name: string;
    description: string;
    icon: React.ReactNode;
    color: string;
    bgColor: string;
    category: 'messaging' | 'productivity' | 'database' | 'custom';
}

const INTEGRATION_TOOLS: IntegrationToolDef[] = [
    // Messaging & Email
    { id: 'gmail', type: 'email', name: 'Gmail', description: 'Send emails via Gmail',
      icon: getVisual('gmail').icon(), color: getVisual('gmail').color, bgColor: getVisual('gmail').bgColor, category: 'messaging' },
    { id: 'slack', type: 'api', name: 'Slack', description: 'Send Slack messages',
      icon: getVisual('slack').icon(), color: getVisual('slack').color, bgColor: getVisual('slack').bgColor, category: 'messaging' },
    { id: 'twilio', type: 'twilio_sms', name: 'Twilio SMS', description: 'Send SMS messages',
      icon: getVisual('twilio').icon(), color: getVisual('twilio').color, bgColor: getVisual('twilio').bgColor, category: 'messaging' },
    { id: 'whatsapp', type: 'api', name: 'WhatsApp', description: 'Send WhatsApp messages',
      icon: getVisual('whatsapp').icon(), color: getVisual('whatsapp').color, bgColor: getVisual('whatsapp').bgColor, category: 'messaging' },
    // Productivity
    { id: 'googlesheets', type: 'google_sheets', name: 'Google Sheets', description: 'Read/write spreadsheets',
      icon: getVisual('googlesheets').icon(), color: getVisual('googlesheets').color, bgColor: getVisual('googlesheets').bgColor, category: 'productivity' },
    { id: 'notion', type: 'api', name: 'Notion', description: 'Manage Notion pages',
      icon: getVisual('notion').icon(), color: getVisual('notion').color, bgColor: getVisual('notion').bgColor, category: 'productivity' },
    { id: 'airtable', type: 'api', name: 'Airtable', description: 'Manage Airtable records',
      icon: getVisual('airtable').icon(), color: getVisual('airtable').color, bgColor: getVisual('airtable').bgColor, category: 'productivity' },
    { id: 'googledrive', type: 'api', name: 'Google Drive', description: 'Upload & manage files',
      icon: getVisual('googledrive').icon(), color: getVisual('googledrive').color, bgColor: getVisual('googledrive').bgColor, category: 'productivity' },
    { id: 'googlecalendar', type: 'google_calendar', name: 'Google Calendar', description: 'Create & find events',
      icon: getVisual('googlecalendar').icon(), color: getVisual('googlecalendar').color, bgColor: getVisual('googlecalendar').bgColor, category: 'productivity' },
    // Developer & CRM
    { id: 'github', type: 'api', name: 'GitHub', description: 'Manage repos & issues',
      icon: getVisual('github').icon(), color: getVisual('github').color, bgColor: getVisual('github').bgColor, category: 'custom' },
    { id: 'hubspot', type: 'api', name: 'HubSpot', description: 'CRM & contacts',
      icon: getVisual('hubspot').icon(), color: getVisual('hubspot').color, bgColor: getVisual('hubspot').bgColor, category: 'custom' },
    { id: 'linear', type: 'api', name: 'Linear', description: 'Create & manage issues',
      icon: getVisual('linear').icon(), color: getVisual('linear').color, bgColor: getVisual('linear').bgColor, category: 'custom' },
    // Database
    { id: 'supabase', type: 'api', name: 'Supabase', description: 'PostgreSQL with auth & storage',
      icon: getVisual('supabase').icon(), color: getVisual('supabase').color, bgColor: getVisual('supabase').bgColor, category: 'database' },
    { id: 'postgresql', type: 'api', name: 'PostgreSQL', description: 'Query PostgreSQL database',
      icon: getVisual('postgresql').icon(), color: getVisual('postgresql').color, bgColor: getVisual('postgresql').bgColor, category: 'database' },
    { id: 'mysql', type: 'api', name: 'MySQL', description: 'Query MySQL database',
      icon: getVisual('mysql').icon(), color: getVisual('mysql').color, bgColor: getVisual('mysql').bgColor, category: 'database' },
    { id: 'mongodb', type: 'api', name: 'MongoDB', description: 'NoSQL document database',
      icon: getVisual('mongodb').icon(), color: getVisual('mongodb').color, bgColor: getVisual('mongodb').bgColor, category: 'database' },
    { id: 'firebase', type: 'api', name: 'Firebase', description: 'Realtime DB & Firestore',
      icon: getVisual('firebase').icon(), color: getVisual('firebase').color, bgColor: getVisual('firebase').bgColor, category: 'database' },
    // Custom APIs & Webhooks
    { id: 'http_api', type: 'api', name: 'HTTP API', description: 'Custom API requests',
      icon: getVisual('http_api').icon(), color: getVisual('http_api').color, bgColor: getVisual('http_api').bgColor, category: 'custom' },
    { id: 'webhook', type: 'api', name: 'Webhook', description: 'Send to webhooks',
      icon: getVisual('webhook').icon(), color: getVisual('webhook').color, bgColor: getVisual('webhook').bgColor, category: 'custom' },
];

export function ToolsPanel({ tools, setTools }: ToolsPanelProps) {
    const { getAccessToken } = useAuth();
    
    // Integration status
    const [integrationStatuses, setIntegrationStatuses] = useState<IntegrationStatus[]>([]);
    const [isLoadingStatuses, setIsLoadingStatuses] = useState(true);

    // Apps connected in the Integrations tab (the only ones we show here).
    const [connectedApps, setConnectedApps] = useState<ConnectedApp[]>([]);

    // Custom tools from library
    const [customToolsLibrary, setCustomToolsLibrary] = useState<CustomToolFromLibrary[]>([]);
    const [isLoadingCustomTools, setIsLoadingCustomTools] = useState(true);

    // Dialog state
    const [configDialogOpen, setConfigDialogOpen] = useState(false);
    const [selectedTool, setSelectedTool] = useState<IntegrationToolDef | null>(null);
    const [editingTool, setEditingTool] = useState<AgentToolReference | null>(null);

    // Integration configs state
    const [twilioConfig, setTwilioConfig] = useState<TwilioSmsConfig>(DEFAULT_TWILIO_SMS_CONFIG);
    const [googleSheetsConfig, setGoogleSheetsConfig] = useState<GoogleSheetsConfig>(DEFAULT_GOOGLE_SHEETS_CONFIG);
    const [googleCalendarConfig, setGoogleCalendarConfig] = useState<GoogleCalendarConfig>(DEFAULT_GOOGLE_CALENDAR_CONFIG);
    const [emailConfig, setEmailConfig] = useState<EmailConfig>(DEFAULT_EMAIL_CONFIG);
    const [mcpConfig, setMcpConfig] = useState<McpServerConfig>(DEFAULT_MCP_SERVER_CONFIG);
    const [functionConfig, setFunctionConfig] = useState<FunctionConfig>(DEFAULT_FUNCTION_CONFIG);
    const [apiConfig, setApiConfig] = useState<ApiToolConfig>(DEFAULT_API_CONFIG);

    // Custom tool form state
    const [showCustomForm, setShowCustomForm] = useState(false);
    const [customForm, setCustomForm] = useState({
        name: '',
        display_name: '',
        description: '',
        method: 'POST',
        url: '',
    });

    // Fetch integration statuses (from both /integrations/status AND /composio/apps)
    useEffect(() => {
        const fetchStatuses = async () => {
            try {
                const accessToken = await getAccessToken();
                const headers = { 'Authorization': `Bearer ${accessToken}` };

                const base = getBackendUrl();
                const [intRes, composioRes] = await Promise.allSettled([
                    fetch(`${base}/api/v1/integrations/status`, { headers }),
                    fetch(`${base}/api/v1/composio/apps`, { headers }),
                ]);

                const statuses: IntegrationStatus[] = [];
                const seen = new Set<string>();

                // Composio apps are the primary source
                const connected: ConnectedApp[] = [];
                if (composioRes.status === 'fulfilled' && composioRes.value.ok) {
                    const apps = await composioRes.value.json();
                    for (const app of apps) {
                        if (app.is_connected || app.status === 'ACTIVE') {
                            statuses.push({
                                integration_id: app.id,
                                is_configured: true,
                                is_enabled: true,
                            });
                            seen.add(app.id);
                            connected.push({
                                id: app.id,
                                name: app.name,
                                description: app.description || '',
                                category: app.category || 'other',
                                logo: app.logo,
                                color: app.color || '#6366F1',
                            });
                        }
                    }
                }
                connected.sort((a, b) => a.name.localeCompare(b.name));
                setConnectedApps(connected);

                // Merge simple integrations for non-Composio tools (webhook, http_api, etc.)
                if (intRes.status === 'fulfilled' && intRes.value.ok) {
                    const data = await intRes.value.json();
                    for (const s of (data.integrations || [])) {
                        if (!seen.has(s.integration_id)) {
                            statuses.push(s);
                            seen.add(s.integration_id);
                        }
                    }
                }

                setIntegrationStatuses(statuses);
            } catch (err) {
                console.error('Failed to fetch integration statuses:', err);
            } finally {
                setIsLoadingStatuses(false);
            }
        };
        fetchStatuses();
    }, [getAccessToken]);

    // Fetch custom tools from library
    useEffect(() => {
        const fetchCustomTools = async () => {
            try {
                const accessToken = await getAccessToken();
                const response = await fetch(`${getBackendUrl()}/api/v1/custom-tools/`, {
                    headers: { 'Authorization': `Bearer ${accessToken}` },
                });
                if (response.ok) {
                    const data = await response.json();
                    setCustomToolsLibrary((data.tools || data || []).filter((t: CustomToolFromLibrary) => t.is_active));
                }
            } catch (err) {
                console.error('Failed to fetch custom tools:', err);
            } finally {
                setIsLoadingCustomTools(false);
            }
        };
        fetchCustomTools();
    }, [getAccessToken]);

    // Check if an integration is configured
    const isIntegrationConfigured = (integrationId: string): boolean => {
        const status = integrationStatuses.find(s => s.integration_id === integrationId);
        return status?.is_configured === true && status?.is_enabled === true;
    };

    const COMPOSIO_APPS = new Set([
        'gmail', 'slack', 'whatsapp', 'notion', 'airtable', 'googledrive',
        'googlesheets', 'googlecalendar', 'github', 'hubspot', 'linear',
    ]);

    const handleAddTool = (tool: IntegrationToolDef) => {
        if (tool.type === 'api' && COMPOSIO_APPS.has(tool.id)) {
            const toolData: AgentToolReference = {
                id: `integration-${Date.now()}`,
                type: 'integration',
                integration_type: 'api',
                composio_app_id: tool.id,
                api: {
                    ...DEFAULT_API_CONFIG,
                    name: tool.id,
                    display_name: tool.name,
                    description: tool.description,
                },
            };
            setTools([...tools, toolData]);
            return;
        }

        setSelectedTool(tool);
        setEditingTool(null);
        setTwilioConfig(DEFAULT_TWILIO_SMS_CONFIG);
        setGoogleSheetsConfig(DEFAULT_GOOGLE_SHEETS_CONFIG);
        setGoogleCalendarConfig(DEFAULT_GOOGLE_CALENDAR_CONFIG);
        setEmailConfig(DEFAULT_EMAIL_CONFIG);
        setMcpConfig(DEFAULT_MCP_SERVER_CONFIG);
        setFunctionConfig(DEFAULT_FUNCTION_CONFIG);
        setApiConfig({
            ...DEFAULT_API_CONFIG,
            name: tool.id,
            display_name: tool.name,
            description: tool.description,
        });
        setConfigDialogOpen(true);
    };

    const handleEditTool = (tool: AgentToolReference) => {
        if (tool.type === 'existing') return; // Custom tools from library are edited on the custom-tools page
        if (tool.type !== 'integration' || !tool.integration_type) return;

        const integrationTool = INTEGRATION_TOOLS.find(t => t.type === tool.integration_type);
        if (!integrationTool) return;

        setSelectedTool(integrationTool);
        setEditingTool(tool);

        // Load existing config
        switch (tool.integration_type) {
            case 'twilio_sms':
                setTwilioConfig(tool.twilio_sms || DEFAULT_TWILIO_SMS_CONFIG);
                break;
            case 'google_sheets':
                setGoogleSheetsConfig(tool.google_sheets || DEFAULT_GOOGLE_SHEETS_CONFIG);
                break;
            case 'google_calendar':
                setGoogleCalendarConfig(tool.google_calendar || DEFAULT_GOOGLE_CALENDAR_CONFIG);
                break;
            case 'email':
                setEmailConfig(tool.email || DEFAULT_EMAIL_CONFIG);
                break;
            case 'mcp_server':
                setMcpConfig(tool.mcp_server || DEFAULT_MCP_SERVER_CONFIG);
                break;
            case 'function':
                setFunctionConfig(tool.function || DEFAULT_FUNCTION_CONFIG);
                break;
            case 'api':
                setApiConfig(tool.api || DEFAULT_API_CONFIG);
                break;
        }
        setConfigDialogOpen(true);
    };

    const handleSaveTool = () => {
        if (!selectedTool) return;

        const toolData: AgentToolReference = {
            id: editingTool?.id || `integration-${Date.now()}`,
            type: 'integration',
            integration_type: selectedTool.type,
        };

        if (COMPOSIO_APPS.has(selectedTool.id)) {
            toolData.composio_app_id = selectedTool.id;
        }

        // Add the specific config based on type
        switch (selectedTool.type) {
            case 'twilio_sms':
                toolData.twilio_sms = twilioConfig;
                break;
            case 'google_sheets':
                toolData.google_sheets = googleSheetsConfig;
                break;
            case 'google_calendar':
                toolData.google_calendar = googleCalendarConfig;
                break;
            case 'email':
                toolData.email = emailConfig;
                break;
            case 'mcp_server':
                toolData.mcp_server = mcpConfig;
                break;
            case 'function':
                toolData.function = functionConfig;
                break;
            case 'api':
                toolData.api = apiConfig;
                break;
        }

        if (editingTool) {
            // Update existing tool
            setTools(tools.map(t => t.id === editingTool.id ? toolData : t));
        } else {
            // Add new tool
            setTools([...tools, toolData]);
        }

        setConfigDialogOpen(false);
        setSelectedTool(null);
        setEditingTool(null);
    };

    const handleRemoveTool = (toolId: string) => {
        setTools(tools.filter(t => t.id !== toolId));
    };

    // Find whether we have a dedicated definition for this app (Gmail, Sheets,
    // Twilio, etc.). Those use purpose-built handlers/config dialogs instead of
    // the generic Composio path.
    const findToolDef = (appId: string) => INTEGRATION_TOOLS.find(t => t.id === appId);

    // Find the already-added tool for a connected app (matching either the
    // generic Composio reference or a dedicated integration_type).
    const findAddedTool = (app: ConnectedApp): AgentToolReference | undefined => {
        const def = findToolDef(app.id);
        return tools.find(t =>
            t.type === 'integration' && (
                t.composio_app_id === app.id ||
                t.api?.name === app.id ||
                (!!def && t.integration_type === def.type && !COMPOSIO_APPS.has(app.id) && def.type !== 'api')
            )
        );
    };

    const isAppAdded = (app: ConnectedApp) => !!findAddedTool(app);

    // Add a connected app: use its dedicated definition when we have one,
    // otherwise register it as a generic Composio-backed tool.
    const handleAddConnectedApp = (app: ConnectedApp) => {
        const def = findToolDef(app.id);
        if (def) {
            handleAddTool(def);
            return;
        }
        const toolData: AgentToolReference = {
            id: `integration-${app.id}-${Date.now()}`,
            type: 'integration',
            integration_type: 'api',
            composio_app_id: app.id,
            api: {
                ...DEFAULT_API_CONFIG,
                name: app.id,
                display_name: app.name,
                description: app.description,
            },
        };
        setTools([...tools, toolData]);
    };

    // Click handler for a connected app row: edit/remove if added, else add.
    const handleConnectedAppClick = (app: ConnectedApp) => {
        const existing = findAddedTool(app);
        if (existing) {
            if (findToolDef(app.id)) {
                handleEditTool(existing);
            } else {
                setTools(tools.filter(t => t.id !== existing.id));
            }
            return;
        }
        handleAddConnectedApp(app);
    };

    // Render an app's logo, falling back to a generic icon.
    const renderAppIcon = (app: { logo?: string; color: string }, sizeClass = 'w-5 h-5') => (
        app.logo ? (
            <img src={app.logo} alt="" className={cn(sizeClass, 'object-contain')} />
        ) : (
            <Globe className={sizeClass} style={{ color: app.color }} />
        )
    );

    const handleToggleCustomTool = (ct: CustomToolFromLibrary) => {
        const existingIdx = tools.findIndex(
            t => t.type === 'existing' && t.tool_id === ct.id
        );
        if (existingIdx >= 0) {
            // Remove it
            setTools(tools.filter((_, i) => i !== existingIdx));
        } else {
            // Add it
            const newRef: AgentToolReference = {
                id: `existing-${ct.id}`,
                type: 'existing',
                tool_id: ct.id,
                tool_name: ct.name,
                tool_display_name: ct.display_name || ct.name,
                llm_description: ct.description,
            };
            setTools([...tools, newRef]);
        }
    };

    const handleAddCustomTool = () => {
        if (!customForm.name || !customForm.display_name || !customForm.description || !customForm.url) {
            return;
        }

        const newTool: AgentToolReference = {
            id: `api-${Date.now()}`,
            type: 'integration',
            integration_type: 'api',
            api: {
                enabled: true,
                name: customForm.name,
                display_name: customForm.display_name,
                description: customForm.description,
                url: customForm.url,
                method: customForm.method as 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
                headers: {},
                body_template: '',
                input_schema: { type: 'object', properties: {}, required: [] },
                timeout_seconds: 30,
            },
        };

        setTools([...tools, newTool]);
        setShowCustomForm(false);
        setCustomForm({
            name: '',
            display_name: '',
            description: '',
            method: 'POST',
            url: '',
        });
    };

    const getToolDisplayInfo = (tool: AgentToolReference) => {
        if (tool.type === 'existing') {
            return {
                name: tool.tool_display_name || tool.tool_name || 'Custom Tool',
                description: tool.llm_description || '',
                icon: <Wrench className="w-5 h-5" />,
                logo: undefined as string | undefined,
                color: 'text-primary',
                bgColor: 'bg-primary/10 hover:bg-primary/20 border-primary/20',
            };
        }

        // Connected Composio app (added from the live integrations list).
        if (tool.type === 'integration' && tool.composio_app_id) {
            const app = connectedApps.find(a => a.id === tool.composio_app_id);
            return {
                name: tool.api?.display_name || app?.name || tool.composio_app_id,
                description: tool.api?.description || app?.description || '',
                icon: <Globe className="w-5 h-5" />,
                logo: app?.logo,
                color: '',
                bgColor: 'bg-primary/10 hover:bg-primary/20 border-primary/20',
            };
        }

        if (tool.type === 'integration' && tool.integration_type) {
            const info = INTEGRATION_TOOLS.find(t => t.type === tool.integration_type);
            let description = '';
            
            switch (tool.integration_type) {
                case 'twilio_sms':
                    description = tool.twilio_sms?.description || 'Send SMS messages';
                    break;
                case 'google_sheets':
                    description = tool.google_sheets?.description || 'Google Sheets';
                    break;
                case 'google_calendar':
                    description = tool.google_calendar?.description || 'Google Calendar';
                    break;
                case 'email':
                    description = tool.email?.description || 'Send emails';
                    break;
                case 'api':
                    description = tool.api?.description || 'API request';
                    break;
                default:
                    description = info?.description || '';
            }

            return {
                name: tool.api?.name || info?.name || tool.integration_type,
                description,
                icon: info?.icon || <Zap className="w-5 h-5" />,
                logo: undefined as string | undefined,
                color: info?.color || 'text-muted-foreground',
                bgColor: info?.bgColor || 'bg-muted',
            };
        }
        
        return {
            name: 'Unknown',
            description: '',
            icon: <Zap className="w-5 h-5" />,
            logo: undefined as string | undefined,
            color: '',
            bgColor: 'bg-muted',
        };
    };

    const renderConfigDialog = () => {
        if (!selectedTool) return null;

        return (
            <Dialog open={configDialogOpen} onOpenChange={setConfigDialogOpen}>
                <DialogContent className="max-w-2xl max-h-[85vh] overflow-hidden flex flex-col">
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-3">
                            <span className={selectedTool.color}>{selectedTool.icon}</span>
                            {editingTool ? 'Edit' : 'Configure'} {selectedTool.name}
                        </DialogTitle>
                        <DialogDescription>
                            Configure how this tool will work during conversations
                        </DialogDescription>
                    </DialogHeader>

                    <div className="flex-1 overflow-y-auto pr-2 py-4">
                        {selectedTool.type === 'twilio_sms' && (
                            <TwilioSmsToolConfig config={twilioConfig} onChange={setTwilioConfig} />
                        )}
                        {selectedTool.type === 'google_sheets' && (
                            <GoogleSheetsToolConfig config={googleSheetsConfig} onChange={setGoogleSheetsConfig} />
                        )}
                        {selectedTool.type === 'google_calendar' && (
                            <GoogleCalendarToolConfig config={googleCalendarConfig} onChange={setGoogleCalendarConfig} />
                        )}
                        {selectedTool.type === 'email' && (
                            <EmailToolConfig config={emailConfig} onChange={setEmailConfig} />
                        )}
                        {selectedTool.type === 'mcp_server' && (
                            <McpServerToolConfig config={mcpConfig} onChange={setMcpConfig} />
                        )}
                        {selectedTool.type === 'function' && (
                            <FunctionToolConfig config={functionConfig} onChange={setFunctionConfig} />
                        )}
                        {selectedTool.type === 'api' && (
                            <ApiToolConfigComponent config={apiConfig} onChange={setApiConfig} />
                        )}
                    </div>

                    <DialogFooter className="border-t pt-4">
                        <Button variant="outline" onClick={() => setConfigDialogOpen(false)}>
                            Cancel
                        </Button>
                        <Button onClick={handleSaveTool}>
                            <Check className="w-4 h-4 mr-2" />
                            {editingTool ? 'Update Tool' : 'Add Tool'}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        );
    };

    return (
        <div className="space-y-5 max-h-[60vh] overflow-y-auto pr-1">
            {/* Header */}
            <div>
                <Label className="text-base font-semibold flex items-center gap-2">
                    <Wrench className="w-4 h-4 text-primary" />
                    Agent Tools
                </Label>
                <p className="text-xs text-muted-foreground mt-1">
                    Choose which tools this agent can use during calls
                </p>
            </div>

            {/* Added tools summary */}
            {tools.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                    {tools.map((tool) => {
                        const info = getToolDisplayInfo(tool);
                        return (
                            <div
                                key={tool.id}
                                className="inline-flex items-center gap-1.5 pl-1.5 pr-2 py-1 rounded-full bg-primary/10 border border-primary/20 text-xs font-medium"
                            >
                                <span className={cn("w-4 h-4 flex items-center justify-center", info.color)}>
                                    {info.logo ? <img src={info.logo} alt="" className="w-4 h-4 object-contain" /> : info.icon}
                                </span>
                                <span className="text-white/90">{info.name}</span>
                                <button
                                    onClick={(e) => { e.stopPropagation(); handleRemoveTool(tool.id); }}
                                    className="ml-0.5 text-muted-foreground hover:text-red-400 transition-colors"
                                >
                                    <X className="w-3 h-3" />
                                </button>
                            </div>
                        );
                    })}
                </div>
            )}

            {/* Connected apps (pulled live from the Integrations tab) */}
            <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2 px-0.5">
                    Connected Apps
                </p>

                {isLoadingStatuses ? (
                    <div className="flex items-center gap-2 px-3 py-6 text-xs text-muted-foreground">
                        <div className="w-3.5 h-3.5 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
                        Loading connected apps…
                    </div>
                ) : connectedApps.length === 0 ? (
                    <Link
                        href="/integrations"
                        target="_blank"
                        className="flex flex-col items-center gap-2 px-3 py-8 rounded-lg text-center border border-dashed border-white/10 hover:border-primary/30 hover:bg-white/[0.02] transition-colors"
                    >
                        <Plug className="w-6 h-6 text-muted-foreground/40" />
                        <span className="text-xs text-muted-foreground">No apps connected yet</span>
                        <span className="text-[11px] text-primary inline-flex items-center gap-1">
                            Connect apps in Integrations <ExternalLink className="w-3 h-3" />
                        </span>
                    </Link>
                ) : (
                    <div className="space-y-1">
                        {connectedApps.map((app) => {
                            const isAdded = isAppAdded(app);
                            const def = findToolDef(app.id);
                            return (
                                <button
                                    key={app.id}
                                    onClick={() => handleConnectedAppClick(app)}
                                    className={cn(
                                        "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-all group",
                                        isAdded
                                            ? "bg-primary/10 border border-primary/25"
                                            : "hover:bg-white/[0.04] border border-transparent hover:border-white/10"
                                    )}
                                >
                                    <div
                                        className={cn(
                                            "w-8 h-8 rounded-lg flex items-center justify-center shrink-0 overflow-hidden",
                                            isAdded ? "bg-primary/15" : "bg-white/[0.06]"
                                        )}
                                    >
                                        {def ? (
                                            <span className={cn("w-4 h-4 flex items-center justify-center", def.color)}>
                                                {def.icon}
                                            </span>
                                        ) : (
                                            renderAppIcon(app, 'w-4 h-4')
                                        )}
                                    </div>

                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2">
                                            <span className="text-sm font-medium text-white/90 truncate">{app.name}</span>
                                            <div className="w-1.5 h-1.5 rounded-full bg-green-400 shrink-0" title="Connected" />
                                        </div>
                                        <p className="text-[11px] text-muted-foreground truncate">{app.description}</p>
                                    </div>

                                    <div className="shrink-0">
                                        {isAdded ? (
                                            <Check className="w-4 h-4 text-primary" />
                                        ) : (
                                            <Plus className="w-4 h-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                                        )}
                                    </div>
                                </button>
                            );
                        })}
                    </div>
                )}
            </div>

            {/* Divider */}
            {(tools.length > 0 || customToolsLibrary.length > 0) && (
                <div className="h-px bg-white/5" />
            )}

            {/* Custom Tools from Library */}
            {!isLoadingCustomTools && customToolsLibrary.length > 0 && (
                <div>
                    <div className="flex items-center justify-between mb-2">
                        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground px-0.5">
                            Your Custom Tools
                        </p>
                        <Link
                            href="/custom-tools"
                            className="text-[11px] text-primary hover:underline inline-flex items-center gap-1"
                        >
                            Manage <ExternalLink className="w-3 h-3" />
                        </Link>
                    </div>
                    <div className="space-y-1">
                        {customToolsLibrary.map((ct) => {
                            const isAdded = tools.some(
                                t => t.type === 'existing' && t.tool_id === ct.id
                            );
                            return (
                                <button
                                    key={ct.id}
                                    onClick={() => handleToggleCustomTool(ct)}
                                    className={cn(
                                        "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-all group",
                                        isAdded
                                            ? "bg-primary/10 border border-primary/25"
                                            : "hover:bg-white/[0.04] border border-transparent hover:border-white/10"
                                    )}
                                >
                                    <div className={cn(
                                        "w-8 h-8 rounded-lg flex items-center justify-center shrink-0",
                                        isAdded ? "bg-primary/15" : "bg-white/[0.06]"
                                    )}>
                                        <Wrench className="w-4 h-4 text-primary" />
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <span className="text-sm font-medium text-white/90 truncate block">{ct.display_name || ct.name}</span>
                                        <p className="text-[11px] text-muted-foreground truncate">{ct.description}</p>
                                    </div>
                                    <div className="shrink-0">
                                        {isAdded ? (
                                            <Check className="w-4 h-4 text-primary" />
                                        ) : (
                                            <Plus className="w-4 h-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                                        )}
                                    </div>
                                </button>
                            );
                        })}
                    </div>
                </div>
            )}
            {!isLoadingCustomTools && customToolsLibrary.length === 0 && (
                <p className="text-xs text-muted-foreground px-0.5">
                    No custom tools.{' '}
                    <Link href="/custom-tools" className="text-primary hover:underline">Create one</Link>
                </p>
            )}

            {/* Custom API/Webhook */}
            <div className="border rounded-lg p-4 space-y-4 bg-muted/10">
                <div className="flex items-center justify-between">
                    <Label className="font-medium flex items-center gap-2">
                        <Code2 className="w-4 h-4" />
                        Custom API / Webhook
                    </Label>
                    {!showCustomForm && (
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setShowCustomForm(true)}
                        >
                            <Plus className="w-4 h-4 mr-1" />
                            Add Custom
                        </Button>
                    )}
                </div>

                {showCustomForm && (
                    <div className="border rounded-md p-4 space-y-3 bg-background/50">
                        <div className="grid grid-cols-2 gap-3">
                            <div className="space-y-1">
                                <Label className="text-xs">Name (identifier)</Label>
                                <Input
                                    placeholder="send_notification"
                                    value={customForm.name}
                                    onChange={(e) => setCustomForm({
                                        ...customForm,
                                        name: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_')
                                    })}
                                />
                            </div>
                            <div className="space-y-1">
                                <Label className="text-xs">Display Name</Label>
                                <Input
                                    placeholder="Send Notification"
                                    value={customForm.display_name}
                                    onChange={(e) => setCustomForm({
                                        ...customForm,
                                        display_name: e.target.value
                                    })}
                                />
                            </div>
                        </div>

                        <div className="space-y-1">
                            <Label className="text-xs">Description (for AI)</Label>
                            <Textarea
                                placeholder="Use this tool when the user wants to..."
                                value={customForm.description}
                                onChange={(e) => setCustomForm({
                                    ...customForm,
                                    description: e.target.value
                                })}
                                className="min-h-[60px]"
                            />
                        </div>

                        <div className="space-y-2 p-3 border rounded bg-muted/30">
                            <Label className="text-xs font-medium">HTTP Configuration</Label>
                            <div className="grid grid-cols-4 gap-2">
                                <Select
                                    value={customForm.method}
                                    onValueChange={(value) => setCustomForm({
                                        ...customForm,
                                        method: value
                                    })}
                                >
                                    <SelectTrigger>
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="GET">GET</SelectItem>
                                        <SelectItem value="POST">POST</SelectItem>
                                        <SelectItem value="PUT">PUT</SelectItem>
                                        <SelectItem value="PATCH">PATCH</SelectItem>
                                        <SelectItem value="DELETE">DELETE</SelectItem>
                                    </SelectContent>
                                </Select>
                                <div className="col-span-3">
                                    <Input
                                        placeholder="https://api.example.com/endpoint"
                                        value={customForm.url}
                                        onChange={(e) => setCustomForm({
                                            ...customForm,
                                            url: e.target.value
                                        })}
                                    />
                                </div>
                            </div>
                        </div>

                        <div className="flex justify-end gap-2 pt-2">
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => setShowCustomForm(false)}
                            >
                                Cancel
                            </Button>
                            <Button
                                size="sm"
                                onClick={handleAddCustomTool}
                                disabled={!customForm.name || !customForm.display_name || !customForm.description || !customForm.url}
                            >
                                Add Tool
                            </Button>
                        </div>
                    </div>
                )}
            </div>

            {/* Link to integrations page */}
            {!isLoadingStatuses && connectedApps.length > 0 && (
                <Link
                    href="/integrations"
                    target="_blank"
                    className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-muted-foreground hover:text-white hover:bg-white/[0.04] transition-colors border border-dashed border-white/10"
                >
                    <ExternalLink className="w-3.5 h-3.5" />
                    Connect more apps in Integrations
                </Link>
            )}

            {/* Config Dialog */}
            {renderConfigDialog()}
        </div>
    );
}
