'use client';

import { ArrowRight, Clock, Globe, Key, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';

import { ApiToolConfig } from '@/components/flow/types';
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
import { Textarea } from '@/components/ui/textarea';

interface ApiToolConfigProps {
    config: ApiToolConfig;
    onChange: (config: ApiToolConfig) => void;
}

const DEFAULT_CONFIG: ApiToolConfig = {
    enabled: true,
    name: '',
    display_name: '',
    description: '',
    method: 'GET',
    url: '',
    headers: {},
    body_template: '',
    input_schema: {
        type: 'object',
        properties: {},
        required: [],
    },
    response_path: '',
    timeout_seconds: 30,
};

const METHOD_COLORS = {
    GET: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20',
    POST: 'bg-blue-500/10 text-blue-500 border-blue-500/20',
    PUT: 'bg-orange-500/10 text-orange-500 border-orange-500/20',
    PATCH: 'bg-yellow-500/10 text-yellow-500 border-yellow-500/20',
    DELETE: 'bg-red-500/10 text-red-500 border-red-500/20',
};

export function ApiToolConfig({ config, onChange }: ApiToolConfigProps) {
    const currentConfig = { ...DEFAULT_CONFIG, ...config };
    const [newHeader, setNewHeader] = useState({ key: '', value: '' });

    const updateConfig = (updates: Partial<ApiToolConfig>) => {
        onChange({ ...currentConfig, ...updates });
    };

    const addHeader = () => {
        if (newHeader.key) {
            updateConfig({
                headers: { ...currentConfig.headers, [newHeader.key]: newHeader.value },
            });
            setNewHeader({ key: '', value: '' });
        }
    };

    const removeHeader = (key: string) => {
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { [key]: _, ...rest } = currentConfig.headers || {};
        updateConfig({ headers: rest });
    };

    return (
        <div className="space-y-5">
            {/* API Identity */}
            <div className="space-y-4 p-4 rounded-lg bg-muted/30 border border-border/50">
                <h4 className="text-sm font-medium flex items-center gap-2">
                    <Globe className="w-4 h-4 text-primary" />
                    API Tool Identity
                </h4>

                <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Tool Name</Label>
                        <Input
                            placeholder="fetch_weather"
                            value={currentConfig.name}
                            onChange={(e) => updateConfig({
                                name: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_')
                            })}
                            className="font-mono text-sm bg-background/50"
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Display Name</Label>
                        <Input
                            placeholder="Fetch Weather"
                            value={currentConfig.display_name}
                            onChange={(e) => updateConfig({ display_name: e.target.value })}
                            className="bg-background/50"
                        />
                    </div>
                </div>

                <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">Description (for AI)</Label>
                    <Textarea
                        placeholder="Fetches current weather data for a given location..."
                        value={currentConfig.description}
                        onChange={(e) => updateConfig({ description: e.target.value })}
                        className="min-h-[60px] bg-background/50"
                    />
                </div>
            </div>

            {/* Request Configuration */}
            <div className="space-y-4">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <ArrowRight className="w-4 h-4 text-cyan-500" />
                    Request Configuration
                </Label>

                <div className="flex gap-2">
                    <Select
                        value={currentConfig.method}
                        onValueChange={(value: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE') =>
                            updateConfig({ method: value })
                        }
                    >
                        <SelectTrigger className={`w-[100px] font-mono font-bold ${METHOD_COLORS[currentConfig.method]}`}>
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
                        placeholder="https://api.example.com/v1/endpoint"
                        value={currentConfig.url}
                        onChange={(e) => updateConfig({ url: e.target.value })}
                        className="flex-1 font-mono text-sm bg-background/50"
                    />
                </div>

                {/* Headers */}
                <div className="space-y-2 p-3 rounded-lg bg-muted/20 border border-border/50">
                    <Label className="text-xs text-muted-foreground flex items-center gap-2">
                        <Key className="w-3 h-3" />
                        Headers
                    </Label>

                    {Object.keys(currentConfig.headers || {}).length > 0 && (
                        <div className="space-y-1">
                            {Object.entries(currentConfig.headers || {}).map(([key, value]) => (
                                <div key={key} className="flex items-center gap-2 text-sm">
                                    <code className="flex-1 px-2 py-1 bg-background/50 rounded text-xs">
                                        {key}: {value}
                                    </code>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        className="h-6 w-6"
                                        onClick={() => removeHeader(key)}
                                    >
                                        <Trash2 className="w-3 h-3" />
                                    </Button>
                                </div>
                            ))}
                        </div>
                    )}

                    <div className="flex gap-2">
                        <Input
                            placeholder="Header-Name"
                            value={newHeader.key}
                            onChange={(e) => setNewHeader({ ...newHeader, key: e.target.value })}
                            className="text-sm bg-background/50"
                        />
                        <Input
                            placeholder="value"
                            value={newHeader.value}
                            onChange={(e) => setNewHeader({ ...newHeader, value: e.target.value })}
                            className="text-sm bg-background/50"
                        />
                        <Button variant="outline" size="sm" onClick={addHeader} disabled={!newHeader.key}>
                            <Plus className="w-3 h-3" />
                        </Button>
                    </div>
                </div>

                {/* Body Template (for POST/PUT/PATCH) */}
                {(['POST', 'PUT', 'PATCH'] as const).includes(currentConfig.method) && (
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Request Body Template</Label>
                        <Textarea
                            placeholder={`{
  "location": "{{city}}",
  "units": "metric"
}`}
                            value={currentConfig.body_template || ''}
                            onChange={(e) => updateConfig({ body_template: e.target.value })}
                            className="font-mono text-xs min-h-[100px] bg-background/50"
                        />
                        <p className="text-xs text-muted-foreground">
                            Use {'{{param_name}}'} for dynamic values from input schema
                        </p>
                    </div>
                )}
            </div>

            {/* Input Schema */}
            <div className="space-y-2">
                <Label className="text-sm font-medium">Input Schema (JSON Schema)</Label>
                <Textarea
                    placeholder={`{
  "type": "object",
  "properties": {
    "city": {
      "type": "string",
      "description": "City name to get weather for"
    }
  },
  "required": ["city"]
}`}
                    value={JSON.stringify(currentConfig.input_schema, null, 2)}
                    onChange={(e) => {
                        try {
                            updateConfig({ input_schema: JSON.parse(e.target.value) });
                        } catch {
                            // Invalid JSON, ignore
                        }
                    }}
                    className="font-mono text-xs min-h-[120px] bg-background/50"
                />
            </div>

            {/* Response & Timeout */}
            <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">Response JSONPath</Label>
                    <Input
                        placeholder="$.data.result"
                        value={currentConfig.response_path || ''}
                        onChange={(e) => updateConfig({ response_path: e.target.value })}
                        className="font-mono text-sm bg-background/50"
                    />
                    <p className="text-xs text-muted-foreground">
                        Extract specific data from response
                    </p>
                </div>
                <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        Timeout (seconds)
                    </Label>
                    <Input
                        type="number"
                        min={1}
                        max={300}
                        value={currentConfig.timeout_seconds}
                        onChange={(e) => updateConfig({ timeout_seconds: parseInt(e.target.value) || 30 })}
                        className="bg-background/50"
                    />
                </div>
            </div>

            {/* Preview Badge */}
            <div className="flex items-center gap-2 p-3 rounded-lg bg-muted/20 border border-border/50">
                <Badge className={METHOD_COLORS[currentConfig.method]}>
                    {currentConfig.method}
                </Badge>
                <span className="text-sm font-mono text-muted-foreground truncate flex-1">
                    {currentConfig.url || 'https://...'}
                </span>
            </div>
        </div>
    );
}

export { DEFAULT_CONFIG as DEFAULT_API_CONFIG };

