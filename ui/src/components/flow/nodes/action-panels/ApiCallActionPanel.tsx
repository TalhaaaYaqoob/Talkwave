'use client';

import { ArrowRight, ChevronDown, ChevronUp, Clock, Globe, Key, Plus, Sparkles, Trash2 } from 'lucide-react';

import { Spinner } from '@/components/ui/ai-loader';
import { useState } from 'react';

import { ApiCallAction } from '@/components/flow/types';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useUserConfig } from '@/context/UserConfigContext';
import { getBackendUrl } from '@/lib/apiClient';

import { VariableChips } from './VariableChips';

interface ApiCallActionPanelProps {
    action: ApiCallAction;
    onChange: (action: ApiCallAction) => void;
    availableVariables?: string[];
}

const METHOD_COLORS = {
    GET: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20',
    POST: 'bg-blue-500/10 text-blue-500 border-blue-500/20',
    PUT: 'bg-orange-500/10 text-orange-500 border-orange-500/20',
    PATCH: 'bg-yellow-500/10 text-yellow-500 border-yellow-500/20',
    DELETE: 'bg-red-500/10 text-red-500 border-red-500/20',
};

export function ApiCallActionPanel({ action, onChange, availableVariables = [] }: ApiCallActionPanelProps) {
    const { accessToken } = useUserConfig();
    const [newHeaderKey, setNewHeaderKey] = useState('');
    const [newHeaderValue, setNewHeaderValue] = useState('');
    const [showAdvanced, setShowAdvanced] = useState(false);
    const [aiDescription, setAiDescription] = useState('');
    const [isGenerating, setIsGenerating] = useState(false);
    const [aiExplanation, setAiExplanation] = useState('');

    const updateAction = (updates: Partial<ApiCallAction>) => {
        onChange({ ...action, ...updates });
    };

    const addHeader = () => {
        if (!newHeaderKey) return;
        updateAction({
            headers: {
                ...action.headers,
                [newHeaderKey]: newHeaderValue,
            },
        });
        setNewHeaderKey('');
        setNewHeaderValue('');
    };

    const removeHeader = (key: string) => {
        const newHeaders = { ...action.headers };
        delete newHeaders[key];
        updateAction({ headers: newHeaders });
    };

    const handleAIGenerate = async () => {
        if (!aiDescription.trim() || !accessToken) return;
        setIsGenerating(true);
        try {
            const baseUrl = getBackendUrl();
            const res = await fetch(`${baseUrl}/api/v1/workflow/ai/action-help`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    action_type: 'api_call',
                    description: aiDescription,
                    action_data: { url: action.url, method: action.method, headers: action.headers },
                    available_variables: availableVariables,
                }),
            });
            if (!res.ok) throw new Error('Failed');
            const data = await res.json();
            if (data.suggestion?.content) {
                const c = data.suggestion.content;
                const updates: Partial<ApiCallAction> = {};
                if (c.url) updates.url = String(c.url);
                if (c.method) updates.method = c.method;
                if (c.headers && typeof c.headers === 'object') updates.headers = { ...action.headers, ...c.headers };
                if (c.body_template != null) updates.body_template = typeof c.body_template === 'string' ? c.body_template : JSON.stringify(c.body_template, null, 2);
                updateAction(updates);
            }
            if (data.suggestion?.explanation) setAiExplanation(data.suggestion.explanation);
        } catch (err) {
            console.error('AI generation failed:', err);
        } finally {
            setIsGenerating(false);
        }
    };

    return (
        <div className="space-y-4">
            {/* Action Name */}
            <div className="space-y-2">
                <Label className="text-sm font-medium">Action Name</Label>
                <Input
                    value={action.name}
                    onChange={(e) => updateAction({ name: e.target.value })}
                    placeholder="Fetch order details"
                    className="bg-background/50"
                />
            </div>

            {/* AI Helper */}
            <div className="space-y-3 p-4 rounded-xl border border-emerald-500/20 bg-emerald-500/5">
                <div className="flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-emerald-400" />
                    <Label className="text-sm font-semibold text-emerald-400">Describe what you need</Label>
                </div>
                <Textarea
                    value={aiDescription}
                    onChange={(e) => setAiDescription(e.target.value)}
                    placeholder="e.g., Send the customer's booking details to my CRM system"
                    className="min-h-[60px] bg-background/50 resize-none text-sm"
                />
                <p className="text-xs text-muted-foreground">
                    Describe in plain English what this API call should do. AI will set up the URL, method, and body for you.
                </p>
                <Button
                    onClick={handleAIGenerate}
                    disabled={isGenerating || !aiDescription.trim()}
                    size="sm"
                    className="w-full gap-2 bg-emerald-600 hover:bg-emerald-700 text-white"
                >
                    {isGenerating ? (
                        <><Spinner size="sm" /> Generating...</>
                    ) : (
                        <><Sparkles className="w-3 h-3" /> Generate with AI</>
                    )}
                </Button>
            </div>

            {/* AI Explanation */}
            {aiExplanation && (
                <div className="p-3 rounded-lg bg-primary/5 border border-primary/20">
                    <p className="text-xs font-semibold text-primary mb-1">What this does:</p>
                    <p className="text-sm text-[#9af8df]/90">{aiExplanation}</p>
                </div>
            )}

            {/* Technical Details (collapsible for non-technical users) */}
            <button
                type="button"
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors w-full"
            >
                {showAdvanced ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                {showAdvanced ? 'Hide' : 'Show'} technical details
            </button>

            {showAdvanced && (
                <div className="space-y-4 pl-2 border-l-2 border-border/30">
                    {/* URL and Method */}
                    <div className="space-y-2">
                        <Label className="text-sm font-medium flex items-center gap-2">
                            <Globe className="w-4 h-4 text-primary" />
                            API Endpoint
                        </Label>
                        <div className="flex gap-2">
                            <Select
                                value={action.method}
                                onValueChange={(value: ApiCallAction['method']) => updateAction({ method: value })}
                            >
                                <SelectTrigger className={`w-[100px] font-mono font-bold ${METHOD_COLORS[action.method]}`}>
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {(['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] as const).map((method) => (
                                        <SelectItem key={method} value={method}>
                                            <span className="font-mono font-bold">{method}</span>
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            <Input
                                value={action.url}
                                onChange={(e) => updateAction({ url: e.target.value })}
                                placeholder="https://api.example.com/v1/orders/{{order_id}}"
                                className="flex-1 font-mono text-sm bg-background/50"
                            />
                        </div>
                    </div>

                    {/* Headers */}
                    <div className="space-y-2 p-3 rounded-lg bg-muted/20 border border-border/50">
                        <Label className="text-xs text-muted-foreground flex items-center gap-2">
                            <Key className="w-3 h-3" />
                            Headers
                        </Label>
                        {Object.entries(action.headers || {}).length > 0 && (
                            <div className="space-y-1">
                                {Object.entries(action.headers || {}).map(([key, value]) => (
                                    <div key={key} className="flex items-center gap-2 text-sm">
                                        <code className="flex-1 px-2 py-1 bg-background/50 rounded text-xs">
                                            {key}: {value}
                                        </code>
                                        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => removeHeader(key)}>
                                            <Trash2 className="w-3 h-3" />
                                        </Button>
                                    </div>
                                ))}
                            </div>
                        )}
                        <div className="flex gap-2">
                            <Input placeholder="Header-Name" value={newHeaderKey} onChange={(e) => setNewHeaderKey(e.target.value)} className="text-sm bg-background/50" />
                            <Input placeholder="value" value={newHeaderValue} onChange={(e) => setNewHeaderValue(e.target.value)} className="text-sm bg-background/50" />
                            <Button variant="outline" size="sm" onClick={addHeader} disabled={!newHeaderKey}><Plus className="w-3 h-3" /></Button>
                        </div>
                    </div>

                    {/* Body Template */}
                    {(['POST', 'PUT', 'PATCH'] as const).includes(action.method) && (
                        <div className="space-y-2">
                            <Label className="text-sm font-medium">Request Body (JSON)</Label>
                            <Textarea
                                value={action.body_template || ''}
                                onChange={(e) => updateAction({ body_template: e.target.value })}
                                placeholder={`{\n  "customer_id": "{{customer_id}}"\n}`}
                                className="min-h-[120px] font-mono text-xs bg-background/50"
                            />
                        </div>
                    )}

                    {/* Timeout */}
                    <div className="space-y-2">
                        <Label className="text-sm font-medium flex items-center gap-2">
                            <Clock className="w-4 h-4 text-muted-foreground" />
                            Timeout (seconds)
                        </Label>
                        <Input
                            type="number" min={1} max={300}
                            value={action.timeout_seconds || 30}
                            onChange={(e) => updateAction({ timeout_seconds: parseInt(e.target.value) || 30 })}
                            className="w-32 bg-background/50"
                        />
                    </div>
                </div>
            )}

            {/* Response Variable */}
            <div className="space-y-2 p-3 rounded-lg bg-primary/5 border border-primary/20">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <ArrowRight className="w-4 h-4 text-primary" />
                    Save Response As
                </Label>
                <Input
                    value={action.response_variable || ''}
                    onChange={(e) => updateAction({ response_variable: e.target.value })}
                    placeholder="api_response"
                    className="font-mono text-sm bg-background/50"
                />
                <p className="text-xs text-muted-foreground">
                    Give the response a name so you can use it later in the conversation
                </p>
            </div>

            {/* Available Variables */}
            <VariableChips variables={availableVariables} label="Available Information" />

            {/* Preview Badge */}
            {action.url && (
                <div className="flex items-center gap-2 p-3 rounded-lg bg-muted/20 border border-border/50">
                    <Badge className={METHOD_COLORS[action.method]}>{action.method}</Badge>
                    <span className="text-sm font-mono text-muted-foreground truncate flex-1">{action.url || 'https://...'}</span>
                </div>
            )}

            {/* Continue on Error */}
            <div className="flex items-center justify-between p-3 rounded-lg bg-muted/20 border border-border/50">
                <div className="space-y-0.5">
                    <Label className="text-sm font-medium">Continue on Error</Label>
                    <p className="text-xs text-muted-foreground">Keep going even if this step fails</p>
                </div>
                <Switch
                    checked={action.continue_on_error ?? false}
                    onCheckedChange={(checked) => updateAction({ continue_on_error: checked })}
                />
            </div>
        </div>
    );
}
