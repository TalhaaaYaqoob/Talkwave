'use client';

import {
    Activity,
    AlertCircle,
    Check,
    ChevronRight,
    Clock,
    Code,
    Database,
    Globe,
    MoreVertical,
    Pencil,
    Play,
    Plus,
    Settings,
    Trash2,
    Webhook,
    Zap
} from 'lucide-react';

import { Spinner } from '@/components/ui/ai-loader';
import { useCallback, useEffect, useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { getBackendUrl } from '@/lib/apiClient';
import { useAuth } from '@/lib/auth';

type ToolType = 'http_request' | 'webhook' | 'database_query' | 'custom_code' | 'integration';

interface CustomTool {
    id: number;
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
    output_schema?: Record<string, unknown>;
    is_active: boolean;
    is_system: boolean;
    timeout_seconds: number;
    created_at: string;
}

interface WebhookEndpoint {
    id: number;
    name: string;
    endpoint_url: string;
    http_method: string;
    auth_type: string | null;
    is_active: boolean;
}

const TOOL_TYPE_ICONS: Record<ToolType, React.ReactNode> = {
    http_request: <Globe className="w-5 h-5" />,
    webhook: <Webhook className="w-5 h-5" />,
    database_query: <Database className="w-5 h-5" />,
    custom_code: <Code className="w-5 h-5" />,
    integration: <Zap className="w-5 h-5" />,
};

const TOOL_TYPE_LABELS: Record<ToolType, string> = {
    http_request: 'HTTP Request',
    webhook: 'Webhook',
    database_query: 'Database Query',
    custom_code: 'Custom Code',
    integration: 'Integration',
};

const TOOL_TYPE_COLORS: Record<ToolType, string> = {
    http_request: 'bg-primary/10 text-primary border-primary/20',
    webhook: 'bg-purple-500/10 text-purple-500 border-purple-500/20',
    database_query: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20',
    custom_code: 'bg-orange-500/10 text-orange-500 border-orange-500/20',
    integration: 'bg-pink-500/10 text-pink-500 border-pink-500/20',
};

const DEFAULT_TOOL_FORM = {
    name: '',
    display_name: '',
    description: '',
    tool_type: 'http_request' as ToolType,
    configuration: {} as Record<string, unknown>,
    input_schema: { type: 'object', properties: {}, required: [] as string[] },
    output_schema: { type: 'object', properties: {} } as Record<string, unknown>,
    timeout_seconds: 30,
};

const DEFAULT_WEBHOOK_FORM = {
    name: '',
    endpoint_url: '',
    http_method: 'POST',
    headers: '{}',
    auth_type: '' as string,
    auth_config: '{}',
};

export default function CustomToolsPage() {
    const { user, getAccessToken } = useAuth();
    const [tools, setTools] = useState<CustomTool[]>([]);
    const [webhooks, setWebhooks] = useState<WebhookEndpoint[]>([]);
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useState('tools');

    // Notifications
    const [notification, setNotification] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

    // Tool CRUD dialogs
    const [createDialogOpen, setCreateDialogOpen] = useState(false);
    const [editDialogOpen, setEditDialogOpen] = useState(false);
    const [testDialogOpen, setTestDialogOpen] = useState(false);
    const [selectedTool, setSelectedTool] = useState<CustomTool | null>(null);
    const [testResult, setTestResult] = useState<Record<string, unknown> | null>(null);
    const [testInput, setTestInput] = useState('{}');
    const [testLoading, setTestLoading] = useState(false);
    const [saving, setSaving] = useState(false);

    // Webhook CRUD dialogs
    const [webhookDialogOpen, setWebhookDialogOpen] = useState(false);
    const [editingWebhook, setEditingWebhook] = useState<WebhookEndpoint | null>(null);
    const [webhookForm, setWebhookForm] = useState(DEFAULT_WEBHOOK_FORM);

    // Tool form state (shared between create/edit)
    const [toolForm, setToolForm] = useState(DEFAULT_TOOL_FORM);

    const showNotification = useCallback((type: 'success' | 'error', message: string) => {
        setNotification({ type, message });
        setTimeout(() => setNotification(null), 4000);
    }, []);

    const fetchTools = useCallback(async () => {
        if (!user) return;
        try {
            const token = await getAccessToken();
            const response = await fetch(`${getBackendUrl()}/api/v1/custom-tools/`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            if (response.ok) {
                const data = await response.json();
                setTools(data.tools || []);
            }
        } catch (error) {
            console.error('Failed to fetch tools:', error);
        }
    }, [user, getAccessToken]);

    const fetchWebhooks = useCallback(async () => {
        if (!user) return;
        try {
            const token = await getAccessToken();
            const response = await fetch(`${getBackendUrl()}/api/v1/custom-tools/webhooks/`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            if (response.ok) {
                const data = await response.json();
                setWebhooks(data || []);
            }
        } catch (error) {
            console.error('Failed to fetch webhooks:', error);
        }
    }, [user, getAccessToken]);

    useEffect(() => {
        const loadData = async () => {
            setLoading(true);
            await Promise.all([fetchTools(), fetchWebhooks()]);
            setLoading(false);
        };
        if (user) loadData();
    }, [user, fetchTools, fetchWebhooks]);

    // ========================
    // Tool CRUD
    // ========================

    const openCreateDialog = () => {
        setToolForm({ ...DEFAULT_TOOL_FORM });
        setCreateDialogOpen(true);
    };

    const openEditDialog = (tool: CustomTool) => {
        setSelectedTool(tool);
        setToolForm({
            name: tool.name,
            display_name: tool.display_name,
            description: tool.description,
            tool_type: tool.tool_type,
            configuration: tool.configuration || {},
            input_schema: {
                type: tool.input_schema?.type || 'object',
                properties: tool.input_schema?.properties || {},
                required: tool.input_schema?.required || [],
            },
            output_schema: tool.output_schema || { type: 'object', properties: {} },
            timeout_seconds: tool.timeout_seconds,
        });
        setEditDialogOpen(true);
    };

    const createTool = async () => {
        if (!user) return;
        setSaving(true);
        try {
            const token = await getAccessToken();
            const response = await fetch(`${getBackendUrl()}/api/v1/custom-tools/`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
                body: JSON.stringify(toolForm),
            });
            if (response.ok) {
                setCreateDialogOpen(false);
                setToolForm({ ...DEFAULT_TOOL_FORM });
                await fetchTools();
                showNotification('success', 'Tool created successfully');
            } else {
                const err = await response.json().catch(() => ({}));
                showNotification('error', (err as Record<string, string>).detail || 'Failed to create tool');
            }
        } catch (error) {
            showNotification('error', `Failed to create tool: ${error}`);
        } finally {
            setSaving(false);
        }
    };

    const updateTool = async () => {
        if (!user || !selectedTool) return;
        setSaving(true);
        try {
            const token = await getAccessToken();
            // Only send editable fields (name and tool_type are immutable after creation)
            const updatePayload = {
                display_name: toolForm.display_name,
                description: toolForm.description,
                configuration: toolForm.configuration,
                input_schema: toolForm.input_schema,
                output_schema: toolForm.output_schema,
                timeout_seconds: toolForm.timeout_seconds,
            };
            const response = await fetch(`${getBackendUrl()}/api/v1/custom-tools/${selectedTool.id}`, {
                method: 'PUT',
                headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
                body: JSON.stringify(updatePayload),
            });
            if (response.ok) {
                setEditDialogOpen(false);
                setSelectedTool(null);
                await fetchTools();
                showNotification('success', 'Tool updated successfully');
            } else {
                const err = await response.json().catch(() => ({}));
                showNotification('error', (err as Record<string, string>).detail || 'Failed to update tool');
            }
        } catch (error) {
            showNotification('error', `Failed to update tool: ${error}`);
        } finally {
            setSaving(false);
        }
    };

    const deleteTool = async (toolId: number) => {
        if (!user) return;
        try {
            const token = await getAccessToken();
            const response = await fetch(`${getBackendUrl()}/api/v1/custom-tools/${toolId}`, {
                method: 'DELETE',
                headers: { Authorization: `Bearer ${token}` },
            });
            if (response.ok) {
                await fetchTools();
                showNotification('success', 'Tool deleted successfully');
            } else {
                showNotification('error', 'Failed to delete tool');
            }
        } catch (error) {
            showNotification('error', `Failed to delete tool: ${error}`);
        }
    };

    // ========================
    // Webhook CRUD
    // ========================

    const openCreateWebhookDialog = () => {
        setEditingWebhook(null);
        setWebhookForm({ ...DEFAULT_WEBHOOK_FORM });
        setWebhookDialogOpen(true);
    };

    const openEditWebhookDialog = (webhook: WebhookEndpoint) => {
        setEditingWebhook(webhook);
        setWebhookForm({
            name: webhook.name,
            endpoint_url: webhook.endpoint_url,
            http_method: webhook.http_method,
            headers: '{}',
            auth_type: webhook.auth_type || '',
            auth_config: '{}',
        });
        setWebhookDialogOpen(true);
    };

    const saveWebhook = async () => {
        if (!user) return;
        setSaving(true);
        try {
            const token = await getAccessToken();
            let parsedHeaders = {};
            let parsedAuthConfig = {};
            try { parsedHeaders = JSON.parse(webhookForm.headers); } catch { /* ignore */ }
            try { parsedAuthConfig = JSON.parse(webhookForm.auth_config); } catch { /* ignore */ }

            const payload = {
                name: webhookForm.name,
                endpoint_url: webhookForm.endpoint_url,
                http_method: webhookForm.http_method,
                headers: parsedHeaders,
                auth_type: webhookForm.auth_type || null,
                auth_config: parsedAuthConfig,
            };

            const base = getBackendUrl();
            const url = editingWebhook
                ? `${base}/api/v1/custom-tools/webhooks/${editingWebhook.id}`
                : `${base}/api/v1/custom-tools/webhooks/`;
            const method = editingWebhook ? 'PUT' : 'POST';

            const response = await fetch(url, {
                method,
                headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            if (response.ok) {
                setWebhookDialogOpen(false);
                await fetchWebhooks();
                showNotification('success', editingWebhook ? 'Webhook updated' : 'Webhook created');
            } else {
                const err = await response.json().catch(() => ({}));
                showNotification('error', (err as Record<string, string>).detail || 'Failed to save webhook');
            }
        } catch (error) {
            showNotification('error', `Failed to save webhook: ${error}`);
        } finally {
            setSaving(false);
        }
    };

    const deleteWebhook = async (webhookId: number) => {
        if (!user) return;
        try {
            const token = await getAccessToken();
            const response = await fetch(`${getBackendUrl()}/api/v1/custom-tools/webhooks/${webhookId}`, {
                method: 'DELETE',
                headers: { Authorization: `Bearer ${token}` },
            });
            if (response.ok) {
                await fetchWebhooks();
                showNotification('success', 'Webhook deleted');
            } else {
                showNotification('error', 'Failed to delete webhook');
            }
        } catch (error) {
            showNotification('error', `Failed to delete webhook: ${error}`);
        }
    };

    // ========================
    // Test
    // ========================

    const testTool = async () => {
        if (!selectedTool || !user) return;
        setTestLoading(true);
        try {
            const token = await getAccessToken();
            const response = await fetch(`${getBackendUrl()}/api/v1/custom-tools/${selectedTool.id}/test`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
                body: JSON.stringify({ input_data: JSON.parse(testInput) }),
            });
            const result = await response.json();
            setTestResult(result);
        } catch (error) {
            setTestResult({ error: String(error) });
        } finally {
            setTestLoading(false);
        }
    };

    const openTestDialog = (tool: CustomTool) => {
        setSelectedTool(tool);
        setTestInput(JSON.stringify(
            Object.fromEntries(
                Object.entries(tool.input_schema.properties || {}).map(([key]) => [key, ''])
            ),
            null,
            2
        ));
        setTestResult(null);
        setTestDialogOpen(true);
    };

    if (loading) {
        return (
            <div className="container mx-auto px-4 py-8">
                <div className="animate-pulse space-y-4">
                    <div className="h-8 w-48 bg-muted rounded" />
                    <div className="h-32 bg-muted rounded" />
                    <div className="h-32 bg-muted rounded" />
                </div>
            </div>
        );
    }

    // Shared tool form renderer (used in both create and edit dialogs)
    const renderToolForm = () => (
        <div className="space-y-4 py-4">
            <div className="grid grid-cols-2 gap-4">
                <div>
                    <Label htmlFor="name">Tool Name (identifier)</Label>
                    <Input
                        id="name"
                        placeholder="get_customer_info"
                        value={toolForm.name}
                        onChange={(e) => setToolForm({ ...toolForm, name: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_') })}
                    />
                    <p className="text-xs text-muted-foreground mt-1">
                        Lowercase letters, numbers, and underscores only
                    </p>
                </div>
                <div>
                    <Label htmlFor="display_name">Display Name</Label>
                    <Input
                        id="display_name"
                        placeholder="Get Customer Info"
                        value={toolForm.display_name}
                        onChange={(e) => setToolForm({ ...toolForm, display_name: e.target.value })}
                    />
                </div>
            </div>
            <div>
                <Label htmlFor="description">Description</Label>
                <Textarea
                    id="description"
                    placeholder="Retrieves customer information from the CRM system..."
                    value={toolForm.description}
                    onChange={(e) => setToolForm({ ...toolForm, description: e.target.value })}
                />
                <p className="text-xs text-muted-foreground mt-1">
                    This description helps the AI understand when to use this tool
                </p>
            </div>
            <div>
                <Label>Tool Type</Label>
                <Select
                    value={toolForm.tool_type}
                    onValueChange={(value: ToolType) => setToolForm({ ...toolForm, tool_type: value })}
                >
                    <SelectTrigger>
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="http_request">
                            <div className="flex items-center gap-2"><Globe className="w-4 h-4" /> HTTP Request</div>
                        </SelectItem>
                        <SelectItem value="webhook">
                            <div className="flex items-center gap-2"><Webhook className="w-4 h-4" /> Webhook</div>
                        </SelectItem>
                        <SelectItem value="database_query">
                            <div className="flex items-center gap-2"><Database className="w-4 h-4" /> Database Query</div>
                        </SelectItem>
                        <SelectItem value="custom_code">
                            <div className="flex items-center gap-2"><Code className="w-4 h-4" /> Custom Code</div>
                        </SelectItem>
                        <SelectItem value="integration">
                            <div className="flex items-center gap-2"><Zap className="w-4 h-4" /> Integration</div>
                        </SelectItem>
                    </SelectContent>
                </Select>
            </div>

            {/* HTTP Request Configuration */}
            {toolForm.tool_type === 'http_request' && (
                <div className="space-y-4 p-4 border rounded-lg bg-muted/30">
                    <h4 className="font-medium">HTTP Request Configuration</h4>
                    <div className="grid grid-cols-3 gap-4">
                        <div>
                            <Label>Method</Label>
                            <Select
                                value={(toolForm.configuration as Record<string, string>).method || 'GET'}
                                onValueChange={(value) => setToolForm({
                                    ...toolForm,
                                    configuration: { ...toolForm.configuration, method: value }
                                })}
                            >
                                <SelectTrigger><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="GET">GET</SelectItem>
                                    <SelectItem value="POST">POST</SelectItem>
                                    <SelectItem value="PUT">PUT</SelectItem>
                                    <SelectItem value="PATCH">PATCH</SelectItem>
                                    <SelectItem value="DELETE">DELETE</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="col-span-2">
                            <Label>URL</Label>
                            <Input
                                placeholder="https://api.example.com/endpoint"
                                value={(toolForm.configuration as Record<string, string>).url || ''}
                                onChange={(e) => setToolForm({
                                    ...toolForm,
                                    configuration: { ...toolForm.configuration, url: e.target.value }
                                })}
                            />
                        </div>
                    </div>
                    <div>
                        <Label>Headers (JSON)</Label>
                        <Textarea
                            placeholder='{"Authorization": "Bearer {{api_key}}"}'
                            value={JSON.stringify((toolForm.configuration as Record<string, unknown>).headers || {}, null, 2)}
                            onChange={(e) => {
                                try {
                                    setToolForm({
                                        ...toolForm,
                                        configuration: { ...toolForm.configuration, headers: JSON.parse(e.target.value) }
                                    });
                                } catch { /* ignore invalid JSON while typing */ }
                            }}
                            className="font-mono text-sm h-20"
                        />
                    </div>
                    <div>
                        <Label>Body Template (JSON with {'{{variable}}'} placeholders)</Label>
                        <Textarea
                            placeholder='{"customer_id": "{{customer_id}}"}'
                            value={(toolForm.configuration as Record<string, string>).body_template || ''}
                            onChange={(e) => setToolForm({
                                ...toolForm,
                                configuration: { ...toolForm.configuration, body_template: e.target.value }
                            })}
                            className="font-mono text-sm"
                        />
                    </div>
                    <div>
                        <Label>Response JSON Path (optional)</Label>
                        <Input
                            placeholder="data.results"
                            value={(toolForm.configuration as Record<string, string>).response_path || ''}
                            onChange={(e) => setToolForm({
                                ...toolForm,
                                configuration: { ...toolForm.configuration, response_path: e.target.value }
                            })}
                        />
                        <p className="text-xs text-muted-foreground mt-1">
                            Extract a specific path from the response (e.g. &quot;data.items&quot;)
                        </p>
                    </div>
                </div>
            )}

            {/* Webhook Configuration */}
            {toolForm.tool_type === 'webhook' && (
                <div className="space-y-4 p-4 border rounded-lg bg-muted/30">
                    <h4 className="font-medium">Webhook Configuration</h4>
                    <div>
                        <Label>Webhook Endpoint</Label>
                        <Select
                            value={String((toolForm.configuration as Record<string, unknown>).webhook_endpoint_id || '')}
                            onValueChange={(value) => setToolForm({
                                ...toolForm,
                                configuration: { ...toolForm.configuration, webhook_endpoint_id: parseInt(value) }
                            })}
                        >
                            <SelectTrigger><SelectValue placeholder="Select a webhook endpoint" /></SelectTrigger>
                            <SelectContent>
                                {webhooks.map(wh => (
                                    <SelectItem key={wh.id} value={String(wh.id)}>
                                        {wh.name} ({wh.http_method} {wh.endpoint_url})
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        {webhooks.length === 0 && (
                            <p className="text-xs text-amber-500 mt-1">
                                No webhook endpoints yet. Create one in the Webhook Endpoints tab first.
                            </p>
                        )}
                    </div>
                    <div>
                        <Label>Payload Template (JSON)</Label>
                        <Textarea
                            placeholder='{"event": "tool_call", "data": "{{input}}"}'
                            value={(toolForm.configuration as Record<string, string>).payload_template || ''}
                            onChange={(e) => setToolForm({
                                ...toolForm,
                                configuration: { ...toolForm.configuration, payload_template: e.target.value }
                            })}
                            className="font-mono text-sm"
                        />
                    </div>
                </div>
            )}

            <div>
                <Label>Input Schema (JSON Schema format)</Label>
                <Textarea
                    placeholder={`{
  "type": "object",
  "properties": {
    "customer_id": {
      "type": "string",
      "description": "The customer ID to lookup"
    }
  },
  "required": ["customer_id"]
}`}
                    value={JSON.stringify(toolForm.input_schema, null, 2)}
                    onChange={(e) => {
                        try { setToolForm({ ...toolForm, input_schema: JSON.parse(e.target.value) }); } catch { /* ignore */ }
                    }}
                    className="font-mono text-sm h-32"
                />
            </div>

            <div>
                <Label>Output Schema (optional, JSON Schema format)</Label>
                <Textarea
                    placeholder={`{
  "type": "object",
  "properties": {
    "result": { "type": "string" }
  }
}`}
                    value={JSON.stringify(toolForm.output_schema, null, 2)}
                    onChange={(e) => {
                        try { setToolForm({ ...toolForm, output_schema: JSON.parse(e.target.value) }); } catch { /* ignore */ }
                    }}
                    className="font-mono text-sm h-24"
                />
            </div>

            <div>
                <Label>Timeout (seconds)</Label>
                <Input
                    type="number"
                    min={1}
                    max={300}
                    value={toolForm.timeout_seconds}
                    onChange={(e) => setToolForm({ ...toolForm, timeout_seconds: parseInt(e.target.value) || 30 })}
                />
            </div>
        </div>
    );

    return (
        <div className="container mx-auto px-4 py-8">
            {/* Notification Toast */}
            {notification && (
                <div className={`fixed top-4 right-4 z-50 p-4 rounded-lg shadow-lg border animate-in fade-in slide-in-from-top-2 ${
                    notification.type === 'success'
                        ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-600 dark:text-emerald-400'
                        : 'bg-red-500/10 border-red-500/20 text-red-600 dark:text-red-400'
                }`}>
                    <div className="flex items-center gap-2">
                        {notification.type === 'success' ? <Check className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
                        {notification.message}
                    </div>
                </div>
            )}

            {/* Header */}
            <div className="flex justify-between items-start mb-8">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight bg-gradient-to-r from-foreground to-foreground/70 bg-clip-text">
                        Custom Tools & Actions
                    </h1>
                    <p className="text-muted-foreground mt-2 max-w-2xl">
                        Extend your AI workflows with custom tools. Create HTTP requests, webhooks,
                        database queries, and more that your AI can use during conversations.
                    </p>
                </div>
                <Button onClick={openCreateDialog} className="gap-2">
                    <Plus className="w-4 h-4" />
                    Create Tool
                </Button>
            </div>

            {/* Stats Cards */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
                <Card className="bg-gradient-to-br from-primary/5 to-primary/10 border-primary/20">
                    <CardContent className="p-4">
                        <div className="flex items-center gap-3">
                            <div className="p-2 rounded-lg bg-primary/10">
                                <Activity className="w-5 h-5 text-primary" />
                            </div>
                            <div>
                                <p className="text-2xl font-bold">{tools.length}</p>
                                <p className="text-sm text-muted-foreground">Total Tools</p>
                            </div>
                        </div>
                    </CardContent>
                </Card>
                <Card className="bg-gradient-to-br from-emerald-500/5 to-emerald-500/10 border-emerald-500/20">
                    <CardContent className="p-4">
                        <div className="flex items-center gap-3">
                            <div className="p-2 rounded-lg bg-emerald-500/10">
                                <Check className="w-5 h-5 text-emerald-500" />
                            </div>
                            <div>
                                <p className="text-2xl font-bold">{tools.filter(t => t.is_active).length}</p>
                                <p className="text-sm text-muted-foreground">Active</p>
                            </div>
                        </div>
                    </CardContent>
                </Card>
                <Card className="bg-gradient-to-br from-purple-500/5 to-purple-500/10 border-purple-500/20">
                    <CardContent className="p-4">
                        <div className="flex items-center gap-3">
                            <div className="p-2 rounded-lg bg-purple-500/10">
                                <Webhook className="w-5 h-5 text-purple-500" />
                            </div>
                            <div>
                                <p className="text-2xl font-bold">{webhooks.length}</p>
                                <p className="text-sm text-muted-foreground">Webhooks</p>
                            </div>
                        </div>
                    </CardContent>
                </Card>
                <Card className="bg-gradient-to-br from-orange-500/5 to-orange-500/10 border-orange-500/20">
                    <CardContent className="p-4">
                        <div className="flex items-center gap-3">
                            <div className="p-2 rounded-lg bg-orange-500/10">
                                <Clock className="w-5 h-5 text-orange-500" />
                            </div>
                            <div>
                                <p className="text-2xl font-bold">30s</p>
                                <p className="text-sm text-muted-foreground">Avg Timeout</p>
                            </div>
                        </div>
                    </CardContent>
                </Card>
            </div>

            {/* Main Content */}
            <Tabs value={activeTab} onValueChange={setActiveTab}>
                <TabsList className="mb-6">
                    <TabsTrigger value="tools" className="gap-2">
                        <Zap className="w-4 h-4" />
                        Tools
                    </TabsTrigger>
                    <TabsTrigger value="webhooks" className="gap-2">
                        <Webhook className="w-4 h-4" />
                        Webhook Endpoints
                    </TabsTrigger>
                    <TabsTrigger value="playground" className="gap-2">
                        <Play className="w-4 h-4" />
                        Playground
                    </TabsTrigger>
                </TabsList>

                {/* Tools Tab */}
                <TabsContent value="tools" className="space-y-4">
                    {tools.length === 0 ? (
                        <Card className="border-dashed">
                            <CardContent className="flex flex-col items-center justify-center py-12">
                                <div className="p-4 rounded-full bg-muted mb-4">
                                    <Zap className="w-8 h-8 text-muted-foreground" />
                                </div>
                                <h3 className="text-lg font-semibold mb-2">No tools yet</h3>
                                <p className="text-muted-foreground text-center max-w-md mb-4">
                                    Create your first custom tool to extend your AI's capabilities.
                                    Tools can make API calls, query databases, or run custom code.
                                </p>
                                <Button onClick={() => setCreateDialogOpen(true)}>
                                    <Plus className="w-4 h-4 mr-2" />
                                    Create Your First Tool
                                </Button>
                            </CardContent>
                        </Card>
                    ) : (
                        <div className="grid gap-4">
                            {tools.map((tool) => (
                                <Card key={tool.id} className="hover:border-primary/50 transition-colors">
                                    <CardContent className="p-4">
                                        <div className="flex items-start justify-between">
                                            <div className="flex items-start gap-4">
                                                <div className={`p-3 rounded-lg ${TOOL_TYPE_COLORS[tool.tool_type]}`}>
                                                    {TOOL_TYPE_ICONS[tool.tool_type]}
                                                </div>
                                                <div>
                                                    <div className="flex items-center gap-2">
                                                        <h3 className="font-semibold">{tool.display_name}</h3>
                                                        <Badge variant={tool.is_active ? 'default' : 'secondary'}>
                                                            {tool.is_active ? 'Active' : 'Inactive'}
                                                        </Badge>
                                                        {tool.is_system && (
                                                            <Badge variant="outline">System</Badge>
                                                        )}
                                                    </div>
                                                    <p className="text-sm text-muted-foreground mt-1">
                                                        {tool.description}
                                                    </p>
                                                    <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
                                                        <span className="flex items-center gap-1">
                                                            <Code className="w-3 h-3" />
                                                            {tool.name}
                                                        </span>
                                                        <span className="flex items-center gap-1">
                                                            <Clock className="w-3 h-3" />
                                                            {tool.timeout_seconds}s timeout
                                                        </span>
                                                        <Badge variant="outline" className="text-xs">
                                                            {TOOL_TYPE_LABELS[tool.tool_type]}
                                                        </Badge>
                                                    </div>
                                                </div>
                                            </div>
                                            <div className="flex items-center gap-2">
                                                <Button
                                                    variant="outline"
                                                    size="sm"
                                                    onClick={() => openTestDialog(tool)}
                                                >
                                                    <Play className="w-4 h-4 mr-1" />
                                                    Test
                                                </Button>
                                                <DropdownMenu>
                                                    <DropdownMenuTrigger asChild>
                                                        <Button variant="ghost" size="icon">
                                                            <MoreVertical className="w-4 h-4" />
                                                        </Button>
                                                    </DropdownMenuTrigger>
                                                    <DropdownMenuContent align="end">
                                                        <DropdownMenuItem onClick={() => openEditDialog(tool)}>
                                                            <Pencil className="w-4 h-4 mr-2" />
                                                            Edit
                                                        </DropdownMenuItem>
                                                        <DropdownMenuItem
                                                            className="text-destructive"
                                                            onClick={() => deleteTool(tool.id)}
                                                            disabled={tool.is_system}
                                                        >
                                                            <Trash2 className="w-4 h-4 mr-2" />
                                                            Delete
                                                        </DropdownMenuItem>
                                                    </DropdownMenuContent>
                                                </DropdownMenu>
                                            </div>
                                        </div>
                                    </CardContent>
                                </Card>
                            ))}
                        </div>
                    )}
                </TabsContent>

                {/* Webhooks Tab */}
                <TabsContent value="webhooks" className="space-y-4">
                    <div className="flex justify-end mb-2">
                        <Button onClick={openCreateWebhookDialog} size="sm" className="gap-2">
                            <Plus className="w-4 h-4" />
                            Create Webhook
                        </Button>
                    </div>
                    {webhooks.length === 0 ? (
                        <Card className="border-dashed">
                            <CardContent className="flex flex-col items-center justify-center py-12">
                                <div className="p-4 rounded-full bg-muted mb-4">
                                    <Webhook className="w-8 h-8 text-muted-foreground" />
                                </div>
                                <h3 className="text-lg font-semibold mb-2">No webhook endpoints</h3>
                                <p className="text-muted-foreground text-center max-w-md mb-4">
                                    Create reusable webhook endpoints that can be used by multiple tools.
                                </p>
                                <Button onClick={openCreateWebhookDialog}>
                                    <Plus className="w-4 h-4 mr-2" />
                                    Create Your First Webhook
                                </Button>
                            </CardContent>
                        </Card>
                    ) : (
                        <div className="space-y-4">
                            {webhooks.map((webhook) => (
                                <Card key={webhook.id}>
                                    <CardContent className="p-4">
                                        <div className="flex items-center justify-between">
                                            <div>
                                                <h3 className="font-semibold">{webhook.name}</h3>
                                                <p className="text-sm text-muted-foreground font-mono">
                                                    {webhook.http_method} {webhook.endpoint_url}
                                                </p>
                                                {webhook.auth_type && (
                                                    <Badge variant="outline" className="text-xs mt-1">
                                                        Auth: {webhook.auth_type}
                                                    </Badge>
                                                )}
                                            </div>
                                            <div className="flex items-center gap-2">
                                                <Badge variant={webhook.is_active ? 'default' : 'secondary'}>
                                                    {webhook.is_active ? 'Active' : 'Inactive'}
                                                </Badge>
                                                <DropdownMenu>
                                                    <DropdownMenuTrigger asChild>
                                                        <Button variant="ghost" size="icon">
                                                            <MoreVertical className="w-4 h-4" />
                                                        </Button>
                                                    </DropdownMenuTrigger>
                                                    <DropdownMenuContent align="end">
                                                        <DropdownMenuItem onClick={() => openEditWebhookDialog(webhook)}>
                                                            <Pencil className="w-4 h-4 mr-2" />
                                                            Edit
                                                        </DropdownMenuItem>
                                                        <DropdownMenuItem
                                                            className="text-destructive"
                                                            onClick={() => deleteWebhook(webhook.id)}
                                                        >
                                                            <Trash2 className="w-4 h-4 mr-2" />
                                                            Delete
                                                        </DropdownMenuItem>
                                                    </DropdownMenuContent>
                                                </DropdownMenu>
                                            </div>
                                        </div>
                                    </CardContent>
                                </Card>
                            ))}
                        </div>
                    )}
                </TabsContent>

                {/* Playground Tab */}
                <TabsContent value="playground">
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <Play className="w-5 h-5" />
                                Tool Playground
                            </CardTitle>
                            <CardDescription>
                                Test your custom tools interactively. Select a tool and provide test input to see how it behaves.
                            </CardDescription>
                        </CardHeader>
                        <CardContent>
                            <div className="grid md:grid-cols-2 gap-6">
                                <div>
                                    <Label className="mb-2 block">Select a Tool</Label>
                                    <div className="space-y-2">
                                        {tools.map((tool) => (
                                            <button
                                                key={tool.id}
                                                onClick={() => openTestDialog(tool)}
                                                className="w-full p-3 rounded-lg border hover:border-primary/50 hover:bg-muted/50 transition-colors text-left flex items-center justify-between"
                                            >
                                                <div className="flex items-center gap-3">
                                                    <div className={`p-2 rounded ${TOOL_TYPE_COLORS[tool.tool_type]}`}>
                                                        {TOOL_TYPE_ICONS[tool.tool_type]}
                                                    </div>
                                                    <div>
                                                        <p className="font-medium">{tool.display_name}</p>
                                                        <p className="text-xs text-muted-foreground">{tool.name}</p>
                                                    </div>
                                                </div>
                                                <ChevronRight className="w-4 h-4 text-muted-foreground" />
                                            </button>
                                        ))}
                                    </div>
                                </div>
                                <div className="bg-muted/30 rounded-lg p-6 flex items-center justify-center">
                                    <div className="text-center">
                                        <AlertCircle className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
                                        <p className="text-muted-foreground">
                                            Select a tool to test its functionality
                                        </p>
                                    </div>
                                </div>
                            </div>
                        </CardContent>
                    </Card>
                </TabsContent>
            </Tabs>

            {/* Create Tool Dialog */}
            <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
                <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
                    <DialogHeader>
                        <DialogTitle>Create Custom Tool</DialogTitle>
                        <DialogDescription>
                            Define a new tool that can be used by your AI during conversations.
                        </DialogDescription>
                    </DialogHeader>
                    {renderToolForm()}
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setCreateDialogOpen(false)}>
                            Cancel
                        </Button>
                        <Button onClick={createTool} disabled={saving || !toolForm.name || !toolForm.display_name || !toolForm.description}>
                            {saving ? <><Spinner size="sm" className="mr-2" /> Creating...</> : 'Create Tool'}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* Edit Tool Dialog */}
            <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
                <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
                    <DialogHeader>
                        <DialogTitle>Edit Tool: {selectedTool?.display_name}</DialogTitle>
                        <DialogDescription>
                            Update the tool configuration. Changes will take effect on the next workflow execution.
                        </DialogDescription>
                    </DialogHeader>
                    {renderToolForm()}
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setEditDialogOpen(false)}>
                            Cancel
                        </Button>
                        <Button onClick={updateTool} disabled={saving || !toolForm.name || !toolForm.display_name || !toolForm.description}>
                            {saving ? <><Spinner size="sm" className="mr-2" /> Saving...</> : 'Save Changes'}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* Webhook Create/Edit Dialog */}
            <Dialog open={webhookDialogOpen} onOpenChange={setWebhookDialogOpen}>
                <DialogContent className="max-w-lg">
                    <DialogHeader>
                        <DialogTitle>{editingWebhook ? 'Edit Webhook' : 'Create Webhook Endpoint'}</DialogTitle>
                        <DialogDescription>
                            {editingWebhook
                                ? 'Update the webhook endpoint configuration.'
                                : 'Create a reusable webhook endpoint that tools can send data to.'}
                        </DialogDescription>
                    </DialogHeader>
                    <div className="space-y-4 py-4">
                        <div>
                            <Label>Name</Label>
                            <Input
                                placeholder="My CRM Webhook"
                                value={webhookForm.name}
                                onChange={(e) => setWebhookForm({ ...webhookForm, name: e.target.value })}
                            />
                        </div>
                        <div className="grid grid-cols-3 gap-4">
                            <div>
                                <Label>Method</Label>
                                <Select
                                    value={webhookForm.http_method}
                                    onValueChange={(value) => setWebhookForm({ ...webhookForm, http_method: value })}
                                >
                                    <SelectTrigger><SelectValue /></SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="GET">GET</SelectItem>
                                        <SelectItem value="POST">POST</SelectItem>
                                        <SelectItem value="PUT">PUT</SelectItem>
                                        <SelectItem value="PATCH">PATCH</SelectItem>
                                        <SelectItem value="DELETE">DELETE</SelectItem>
                                    </SelectContent>
                                </Select>
                            </div>
                            <div className="col-span-2">
                                <Label>Endpoint URL</Label>
                                <Input
                                    placeholder="https://hooks.example.com/webhook"
                                    value={webhookForm.endpoint_url}
                                    onChange={(e) => setWebhookForm({ ...webhookForm, endpoint_url: e.target.value })}
                                />
                            </div>
                        </div>
                        <div>
                            <Label>Headers (JSON)</Label>
                            <Textarea
                                placeholder='{"Content-Type": "application/json"}'
                                value={webhookForm.headers}
                                onChange={(e) => setWebhookForm({ ...webhookForm, headers: e.target.value })}
                                className="font-mono text-sm h-20"
                            />
                        </div>
                        <div>
                            <Label>Auth Type (optional)</Label>
                            <Select
                                value={webhookForm.auth_type || '_none'}
                                onValueChange={(value) => setWebhookForm({ ...webhookForm, auth_type: value === '_none' ? '' : value })}
                            >
                                <SelectTrigger><SelectValue placeholder="None" /></SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="_none">None</SelectItem>
                                    <SelectItem value="bearer">Bearer Token</SelectItem>
                                    <SelectItem value="basic">Basic Auth</SelectItem>
                                    <SelectItem value="api_key">API Key Header</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        {webhookForm.auth_type && (
                            <div>
                                <Label>Auth Config (JSON)</Label>
                                <Textarea
                                    placeholder={
                                        webhookForm.auth_type === 'bearer'
                                            ? '{"token": "your-token"}'
                                            : webhookForm.auth_type === 'basic'
                                            ? '{"username": "user", "password": "pass"}'
                                            : '{"header_name": "X-API-Key", "api_key": "key"}'
                                    }
                                    value={webhookForm.auth_config}
                                    onChange={(e) => setWebhookForm({ ...webhookForm, auth_config: e.target.value })}
                                    className="font-mono text-sm h-20"
                                />
                            </div>
                        )}
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setWebhookDialogOpen(false)}>
                            Cancel
                        </Button>
                        <Button
                            onClick={saveWebhook}
                            disabled={saving || !webhookForm.name || !webhookForm.endpoint_url}
                        >
                            {saving
                                ? <><Spinner size="sm" className="mr-2" /> Saving...</>
                                : editingWebhook ? 'Update Webhook' : 'Create Webhook'}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* Test Tool Dialog */}
            <Dialog open={testDialogOpen} onOpenChange={setTestDialogOpen}>
                <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-2">
                            <Play className="w-5 h-5" />
                            Test Tool: {selectedTool?.display_name}
                        </DialogTitle>
                        <DialogDescription>
                            Provide test input data to execute this tool and see the result.
                        </DialogDescription>
                    </DialogHeader>
                    <div className="grid md:grid-cols-2 gap-6 py-4">
                        <div>
                            <Label className="mb-2 block">Input Data (JSON)</Label>
                            <Textarea
                                value={testInput}
                                onChange={(e) => setTestInput(e.target.value)}
                                className="font-mono text-sm h-64"
                                placeholder='{"key": "value"}'
                            />
                            {selectedTool && (
                                <div className="mt-4 p-3 bg-muted rounded-lg">
                                    <p className="text-xs font-medium text-muted-foreground mb-2">Expected Input Parameters:</p>
                                    <ul className="text-xs space-y-1">
                                        {Object.entries(selectedTool.input_schema.properties || {}).map(([key, schema]) => (
                                            <li key={key} className="flex items-center gap-2">
                                                <code className="px-1 bg-background rounded">{key}</code>
                                                <span className="text-muted-foreground">({schema.type})</span>
                                                {selectedTool.input_schema.required?.includes(key) && (
                                                    <Badge variant="outline" className="text-xs">required</Badge>
                                                )}
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                        </div>
                        <div>
                            <Label className="mb-2 block">Result</Label>
                            <div className="h-64 overflow-auto bg-muted rounded-lg p-4 font-mono text-sm">
                                {testLoading ? (
                                    <div className="flex items-center gap-2 text-muted-foreground">
                                        <div className="animate-spin w-4 h-4 border-2 border-primary border-t-transparent rounded-full" />
                                        Executing...
                                    </div>
                                ) : testResult !== null ? (
                                    <pre className="whitespace-pre-wrap break-words">
                                        {JSON.stringify(testResult, null, 2)}
                                    </pre>
                                ) : (
                                    <span className="text-muted-foreground">
                                        Click "Run Test" to see results
                                    </span>
                                )}
                            </div>
                            {testResult && (
                                <div className="mt-2 flex items-center gap-2">
                                    {testResult.status === 'success' ? (
                                        <Badge className="bg-emerald-500/10 text-emerald-500 border-emerald-500/20">
                                            <Check className="w-3 h-3 mr-1" />
                                            Success
                                        </Badge>
                                    ) : (
                                        <Badge className="bg-red-500/10 text-red-500 border-red-500/20">
                                            <AlertCircle className="w-3 h-3 mr-1" />
                                            Error
                                        </Badge>
                                    )}
                                    {typeof testResult.execution_time_ms === 'number' && (
                                        <span className="text-xs text-muted-foreground">
                                            {testResult.execution_time_ms}ms
                                        </span>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setTestDialogOpen(false)}>
                            Close
                        </Button>
                        <Button onClick={testTool} disabled={testLoading}>
                            {testLoading ? (
                                <>
                                    <div className="animate-spin w-4 h-4 border-2 border-primary-foreground border-t-transparent rounded-full mr-2" />
                                    Running...
                                </>
                            ) : (
                                <>
                                    <Play className="w-4 h-4 mr-2" />
                                    Run Test
                                </>
                            )}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}

