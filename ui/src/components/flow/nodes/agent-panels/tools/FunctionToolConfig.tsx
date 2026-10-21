'use client';

import { Braces, Code2, Plus, Trash2, Variable, Webhook } from 'lucide-react';
import { useState } from 'react';

import { FunctionConfig } from '@/components/flow/types';
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

interface FunctionToolConfigProps {
    config: FunctionConfig;
    onChange: (config: FunctionConfig) => void;
}

const DEFAULT_CONFIG: FunctionConfig = {
    enabled: true,
    name: '',
    display_name: '',
    description: '',
    parameters: {
        type: 'object',
        properties: {},
        required: [],
    },
    handler_type: 'webhook',
    webhook_url: '',
    response_template: '',
};

interface ParameterInput {
    name: string;
    type: string;
    description: string;
    required: boolean;
}

export function FunctionToolConfig({ config, onChange }: FunctionToolConfigProps) {
    const currentConfig = { ...DEFAULT_CONFIG, ...config };
    const [newParam, setNewParam] = useState<ParameterInput>({
        name: '',
        type: 'string',
        description: '',
        required: true,
    });

    const updateConfig = (updates: Partial<FunctionConfig>) => {
        onChange({ ...currentConfig, ...updates });
    };

    const addParameter = () => {
        if (!newParam.name) return;

        const newProperties = {
            ...currentConfig.parameters.properties,
            [newParam.name]: {
                type: newParam.type,
                description: newParam.description,
            },
        };
        const newRequired = newParam.required
            ? [...currentConfig.parameters.required, newParam.name]
            : currentConfig.parameters.required;

        updateConfig({
            parameters: {
                ...currentConfig.parameters,
                properties: newProperties,
                required: newRequired,
            },
        });

        setNewParam({ name: '', type: 'string', description: '', required: true });
    };

    const removeParameter = (paramName: string) => {
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { [paramName]: _, ...newProperties } = currentConfig.parameters.properties;
        updateConfig({
            parameters: {
                ...currentConfig.parameters,
                properties: newProperties,
                required: currentConfig.parameters.required.filter(r => r !== paramName),
            },
        });
    };

    return (
        <div className="space-y-5">
            {/* Function Identity */}
            <div className="space-y-4 p-4 rounded-lg bg-muted/30 border border-border/50">
                <h4 className="text-sm font-medium flex items-center gap-2">
                    <Code2 className="w-4 h-4 text-cyan-500" />
                    Function Identity
                </h4>

                <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Function Name</Label>
                        <Input
                            placeholder="get_order_status"
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
                            placeholder="Get Order Status"
                            value={currentConfig.display_name}
                            onChange={(e) => updateConfig({ display_name: e.target.value })}
                            className="bg-background/50"
                        />
                    </div>
                </div>

                <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">Description (for AI)</Label>
                    <Textarea
                        placeholder="Retrieves the current status of an order by its ID..."
                        value={currentConfig.description}
                        onChange={(e) => updateConfig({ description: e.target.value })}
                        className="min-h-[60px] bg-background/50"
                    />
                </div>
            </div>

            {/* Parameters */}
            <div className="space-y-3">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <Variable className="w-4 h-4 text-orange-500" />
                    Parameters
                </Label>

                {/* Current Parameters */}
                {Object.keys(currentConfig.parameters.properties).length > 0 && (
                    <div className="space-y-2">
                        {Object.entries(currentConfig.parameters.properties).map(([name, param]) => (
                            <div
                                key={name}
                                className="flex items-center justify-between p-3 rounded-lg bg-background/50 border border-border/50"
                            >
                                <div className="flex items-center gap-3">
                                    <code className="text-sm font-mono text-cyan-400">{name}</code>
                                    <Badge variant="outline" className="text-xs">
                                        {param.type}
                                    </Badge>
                                    {currentConfig.parameters.required.includes(name) && (
                                        <Badge variant="secondary" className="text-xs bg-orange-500/10 text-orange-400">
                                            required
                                        </Badge>
                                    )}
                                </div>
                                <div className="flex items-center gap-2">
                                    <span className="text-xs text-muted-foreground max-w-[200px] truncate">
                                        {param.description}
                                    </span>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        className="h-7 w-7"
                                        onClick={() => removeParameter(name)}
                                    >
                                        <Trash2 className="w-3 h-3" />
                                    </Button>
                                </div>
                            </div>
                        ))}
                    </div>
                )}

                {/* Add Parameter Form */}
                <div className="p-3 rounded-lg bg-muted/30 border border-dashed border-border/50 space-y-3">
                    <div className="grid grid-cols-4 gap-2">
                        <Input
                            placeholder="param_name"
                            value={newParam.name}
                            onChange={(e) => setNewParam({
                                ...newParam,
                                name: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_')
                            })}
                            className="font-mono text-sm bg-background/50"
                        />
                        <Select
                            value={newParam.type}
                            onValueChange={(value) => setNewParam({ ...newParam, type: value })}
                        >
                            <SelectTrigger className="bg-background/50">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="string">string</SelectItem>
                                <SelectItem value="number">number</SelectItem>
                                <SelectItem value="boolean">boolean</SelectItem>
                                <SelectItem value="array">array</SelectItem>
                                <SelectItem value="object">object</SelectItem>
                            </SelectContent>
                        </Select>
                        <Input
                            placeholder="Description..."
                            value={newParam.description}
                            onChange={(e) => setNewParam({ ...newParam, description: e.target.value })}
                            className="bg-background/50"
                        />
                        <Button
                            variant="outline"
                            onClick={addParameter}
                            disabled={!newParam.name}
                        >
                            <Plus className="w-4 h-4 mr-1" />
                            Add
                        </Button>
                    </div>
                    <label className="flex items-center gap-2 text-xs">
                        <input
                            type="checkbox"
                            checked={newParam.required}
                            onChange={(e) => setNewParam({ ...newParam, required: e.target.checked })}
                            className="rounded"
                        />
                        Required parameter
                    </label>
                </div>
            </div>

            {/* Handler Configuration */}
            <div className="space-y-4 p-4 rounded-lg bg-muted/30 border border-border/50">
                <h4 className="text-sm font-medium flex items-center gap-2">
                    <Braces className="w-4 h-4 text-green-500" />
                    Function Handler
                </h4>

                <div className="grid grid-cols-2 gap-4">
                    {(['webhook', 'inline_response'] as const).map((type) => (
                        <button
                            key={type}
                            type="button"
                            onClick={() => updateConfig({ handler_type: type })}
                            className={`
                                p-3 rounded-lg border text-left transition-all
                                ${currentConfig.handler_type === type
                                    ? 'border-cyan-500/50 bg-cyan-500/10 ring-1 ring-cyan-500/30'
                                    : 'border-border/50 bg-background/50 hover:border-border'}
                            `}
                        >
                            <div className="flex items-center gap-2 mb-1">
                                {type === 'webhook' ? (
                                    <Webhook className="w-4 h-4" />
                                ) : (
                                    <Code2 className="w-4 h-4" />
                                )}
                                <span className="font-medium text-sm">
                                    {type === 'webhook' ? 'Webhook' : 'Inline Response'}
                                </span>
                            </div>
                            <p className="text-xs text-muted-foreground">
                                {type === 'webhook'
                                    ? 'Call external API to handle the function'
                                    : 'Return templated response immediately'
                                }
                            </p>
                        </button>
                    ))}
                </div>

                {currentConfig.handler_type === 'webhook' && (
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Webhook URL</Label>
                        <Input
                            placeholder="https://api.example.com/function/handle"
                            value={currentConfig.webhook_url || ''}
                            onChange={(e) => updateConfig({ webhook_url: e.target.value })}
                            className="font-mono text-sm bg-background/50"
                        />
                    </div>
                )}

                {currentConfig.handler_type === 'inline_response' && (
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Response Template</Label>
                        <Textarea
                            placeholder='{"status": "success", "message": "Order {{order_id}} is being processed"}'
                            value={currentConfig.response_template || ''}
                            onChange={(e) => updateConfig({ response_template: e.target.value })}
                            className="font-mono text-xs min-h-[80px] bg-background/50"
                        />
                        <p className="text-xs text-muted-foreground">
                            Use {'{{param_name}}'} to include function parameters in the response
                        </p>
                    </div>
                )}
            </div>
        </div>
    );
}

export { DEFAULT_CONFIG as DEFAULT_FUNCTION_CONFIG };

