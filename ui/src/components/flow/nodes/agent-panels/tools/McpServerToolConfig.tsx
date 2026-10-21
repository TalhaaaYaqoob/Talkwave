'use client';

import { Check, Key, Link, Plus, Server, Trash2, Wrench } from 'lucide-react';
import { useState } from 'react';

import { McpServerConfig } from '@/components/flow/types';
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

interface McpServerToolConfigProps {
    config: McpServerConfig;
    onChange: (config: McpServerConfig) => void;
}

const DEFAULT_CONFIG: McpServerConfig = {
    enabled: true,
    description: 'Connect to MCP server for advanced tool capabilities',
    server_name: '',
    server_url: '',
    tools: [],
    auth_type: 'none',
};

export function McpServerToolConfig({ config, onChange }: McpServerToolConfigProps) {
    const currentConfig = { ...DEFAULT_CONFIG, ...config };
    const [newTool, setNewTool] = useState('');

    const updateConfig = (updates: Partial<McpServerConfig>) => {
        onChange({ ...currentConfig, ...updates });
    };

    const addTool = () => {
        if (newTool && !currentConfig.tools.includes(newTool)) {
            updateConfig({ tools: [...currentConfig.tools, newTool] });
            setNewTool('');
        }
    };

    const removeTool = (tool: string) => {
        updateConfig({ tools: currentConfig.tools.filter(t => t !== tool) });
    };

    return (
        <div className="space-y-5">
            {/* Description */}
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <Server className="w-4 h-4 text-purple-500" />
                    Tool Description (for AI)
                </Label>
                <Textarea
                    placeholder="Describe the MCP server capabilities and when to use them..."
                    value={currentConfig.description}
                    onChange={(e) => updateConfig({ description: e.target.value })}
                    className="min-h-[80px] bg-background/50 border-border/50 focus:border-purple-500/50"
                />
            </div>

            {/* Server Configuration */}
            <div className="space-y-4 p-4 rounded-lg bg-muted/30 border border-border/50">
                <h4 className="text-sm font-medium flex items-center gap-2">
                    <Link className="w-4 h-4 text-primary" />
                    Server Connection
                </h4>

                <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Server Name</Label>
                        <Input
                            placeholder="my-mcp-server"
                            value={currentConfig.server_name}
                            onChange={(e) => updateConfig({ server_name: e.target.value })}
                            className="bg-background/50"
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Authentication</Label>
                        <Select
                            value={currentConfig.auth_type}
                            onValueChange={(value: 'none' | 'bearer' | 'api_key') =>
                                updateConfig({ auth_type: value })
                            }
                        >
                            <SelectTrigger className="bg-background/50">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="none">No Auth</SelectItem>
                                <SelectItem value="bearer">Bearer Token</SelectItem>
                                <SelectItem value="api_key">API Key</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>
                </div>

                <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">Server URL</Label>
                    <Input
                        placeholder="https://mcp.example.com or stdio://path/to/server"
                        value={currentConfig.server_url}
                        onChange={(e) => updateConfig({ server_url: e.target.value })}
                        className="font-mono text-sm bg-background/50"
                    />
                </div>

                {currentConfig.auth_type !== 'none' && (
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground flex items-center gap-2">
                            <Key className="w-3 h-3" />
                            {currentConfig.auth_type === 'bearer' ? 'Bearer Token' : 'API Key'}
                        </Label>
                        <Input
                            type="password"
                            placeholder="Enter your token..."
                            value={currentConfig.auth_token || ''}
                            onChange={(e) => updateConfig({ auth_token: e.target.value })}
                            className="font-mono text-sm bg-background/50"
                        />
                    </div>
                )}
            </div>

            {/* Tools Selection */}
            <div className="space-y-3">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <Wrench className="w-4 h-4 text-orange-500" />
                    Available Tools
                </Label>

                {/* Tool List */}
                {currentConfig.tools.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                        {currentConfig.tools.map((tool) => (
                            <Badge
                                key={tool}
                                variant="secondary"
                                className="pl-3 pr-1 py-1.5 gap-2 bg-purple-500/10 text-purple-400 border-purple-500/20"
                            >
                                <Check className="w-3 h-3" />
                                {tool}
                                <button
                                    onClick={() => removeTool(tool)}
                                    className="p-0.5 rounded hover:bg-destructive/20 transition-colors"
                                >
                                    <Trash2 className="w-3 h-3" />
                                </button>
                            </Badge>
                        ))}
                    </div>
                ) : (
                    <p className="text-sm text-muted-foreground">No tools selected yet</p>
                )}

                {/* Add Tool */}
                <div className="flex gap-2">
                    <Input
                        placeholder="Enter tool name..."
                        value={newTool}
                        onChange={(e) => setNewTool(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && addTool()}
                        className="bg-background/50"
                    />
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={addTool}
                        disabled={!newTool}
                    >
                        <Plus className="w-4 h-4 mr-1" />
                        Add
                    </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                    Add tool names that the MCP server exposes. Use * to allow all tools.
                </p>
            </div>

            {/* Info Box */}
            <div className="p-3 rounded-lg bg-purple-500/5 border border-purple-500/20">
                <p className="text-xs text-purple-400">
                    <strong>MCP (Model Context Protocol)</strong> enables your AI agent to connect to external tool servers.
                    The server will provide tool definitions and handle tool execution.
                </p>
            </div>
        </div>
    );
}

export { DEFAULT_CONFIG as DEFAULT_MCP_SERVER_CONFIG };

