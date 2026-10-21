'use client';

import { ChevronDown, ChevronUp, Database, Sparkles, Table2 } from 'lucide-react';

import { Spinner } from '@/components/ui/ai-loader';
import { useState } from 'react';

import { DatabaseQueryAction } from '@/components/flow/types';
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

interface DatabaseQueryActionPanelProps {
    action: DatabaseQueryAction;
    onChange: (action: DatabaseQueryAction) => void;
    availableVariables?: string[];
}

const DB_LABELS: Record<string, { name: string; color: string }> = {
    postgresql: { name: 'PostgreSQL', color: 'text-blue-400' },
    mysql: { name: 'MySQL', color: 'text-orange-400' },
    mongodb: { name: 'MongoDB', color: 'text-green-400' },
    supabase: { name: 'Supabase', color: 'text-emerald-400' },
    firebase: { name: 'Firebase', color: 'text-amber-400' },
    redis: { name: 'Redis', color: 'text-red-400' },
};

const FRIENDLY_OPERATIONS = [
    { value: 'query', label: 'Look up data', description: 'Find and read records from your database' },
    { value: 'insert', label: 'Save new data', description: 'Add a new record to your database' },
    { value: 'update', label: 'Update existing data', description: 'Change an existing record' },
    { value: 'delete', label: 'Remove data', description: 'Delete a record from your database' },
];

export function DatabaseQueryActionPanel({ action, onChange, availableVariables = [] }: DatabaseQueryActionPanelProps) {
    const { accessToken } = useUserConfig();
    const [isGenerating, setIsGenerating] = useState(false);
    const [showAdvanced, setShowAdvanced] = useState(false);

    const updateAction = (updates: Partial<DatabaseQueryAction>) => {
        onChange({ ...action, ...updates });
    };

    const dbInfo = DB_LABELS[action.database_service] || { name: action.database_service || 'Database', color: 'text-muted-foreground' };

    const handleGenerateQuery = async () => {
        if (!action.description?.trim() || !accessToken) return;
        setIsGenerating(true);
        try {
            const baseUrl = getBackendUrl();
            const res = await fetch(`${baseUrl}/api/v1/workflow/ai/action-help`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    action_type: 'database_query',
                    description: action.description,
                    database_service: action.database_service,
                    table_name: action.table_name || '',
                    operation: action.operation,
                    available_variables: availableVariables,
                }),
            });
            if (!res.ok) throw new Error('Failed to generate');
            const data = await res.json();
            if (data.suggestion) {
                updateAction({
                    query_template: data.suggestion.query_template || action.query_template,
                    ai_explanation: data.suggestion.explanation || '',
                });
            }
        } catch (err) {
            console.error('AI query generation failed:', err);
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
                    placeholder="Save customer booking"
                    className="bg-background/50"
                />
            </div>

            {/* Connected Database Badge */}
            <div className="flex items-center gap-2 p-3 rounded-lg bg-muted/20 border border-border/50">
                <Database className={`w-4 h-4 ${dbInfo.color}`} />
                <span className="text-sm font-medium">Connected to</span>
                <span className={`text-sm font-semibold ${dbInfo.color}`}>{dbInfo.name}</span>
            </div>

            {/* Table / Collection Name */}
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <Table2 className="w-4 h-4 text-purple-400" />
                    {action.database_service === 'mongodb' ? 'Collection Name' :
                     action.database_service === 'firebase' ? 'Document Path' :
                     'Table Name'}
                </Label>
                <Input
                    value={action.table_name || ''}
                    onChange={(e) => updateAction({ table_name: e.target.value })}
                    placeholder={
                        action.database_service === 'mongodb' ? 'e.g., appointments' :
                        action.database_service === 'firebase' ? 'e.g., users/appointments' :
                        'e.g., appointments'
                    }
                    className="bg-background/50"
                />
                <p className="text-xs text-muted-foreground">
                    {action.database_service === 'mongodb'
                        ? 'The name of the collection where your data is stored'
                        : action.database_service === 'firebase'
                        ? 'The path to your document or collection in Firebase'
                        : 'The name of the table where your data is stored'}
                </p>
            </div>

            {/* Operation - Friendly labels */}
            <div className="space-y-2">
                <Label className="text-sm font-medium">What do you want to do?</Label>
                <Select
                    value={action.operation}
                    onValueChange={(value: 'query' | 'insert' | 'update' | 'delete') =>
                        updateAction({ operation: value })
                    }
                >
                    <SelectTrigger className="bg-background/50">
                        <SelectValue placeholder="Choose an operation" />
                    </SelectTrigger>
                    <SelectContent>
                        {FRIENDLY_OPERATIONS.map((op) => (
                            <SelectItem key={op.value} value={op.value}>
                                <div className="flex flex-col">
                                    <span className="font-medium">{op.label}</span>
                                    <span className="text-xs text-muted-foreground">{op.description}</span>
                                </div>
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            </div>

            {/* AI Query Generator */}
            <div className="space-y-3 p-4 rounded-xl border border-emerald-500/20 bg-emerald-500/5">
                <div className="flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-emerald-400" />
                    <Label className="text-sm font-semibold text-emerald-400">Describe what you need</Label>
                </div>
                <Textarea
                    value={action.description || ''}
                    onChange={(e) => updateAction({ description: e.target.value })}
                    placeholder={
                        action.operation === 'query'
                            ? "e.g., Find all appointments for this customer's phone number"
                            : action.operation === 'insert'
                            ? "e.g., Save the customer's name, phone number, and appointment date"
                            : action.operation === 'update'
                            ? "e.g., Update the appointment status to confirmed for this customer"
                            : "e.g., Remove the appointment for this customer's phone number"
                    }
                    className="min-h-[80px] bg-background/50 resize-none"
                />
                <p className="text-xs text-muted-foreground">
                    Tell us in your own words what data you want to {
                        action.operation === 'query' ? 'find' :
                        action.operation === 'insert' ? 'save' :
                        action.operation === 'update' ? 'change' : 'remove'
                    }. Our AI will create the right query for you.
                </p>

                <Button
                    onClick={handleGenerateQuery}
                    disabled={isGenerating || !action.description?.trim()}
                    className="w-full gap-2 bg-emerald-600 hover:bg-emerald-700 text-white"
                >
                    {isGenerating ? (
                        <>
                            <Spinner size="sm" />
                            Generating...
                        </>
                    ) : (
                        <>
                            <Sparkles className="w-4 h-4" />
                            Generate with AI
                        </>
                    )}
                </Button>
            </div>

            {/* AI Explanation */}
            {action.ai_explanation && (
                <div className="p-3 rounded-lg bg-primary/5 border border-primary/20">
                    <p className="text-xs font-semibold text-primary mb-1">What this does:</p>
                    <p className="text-sm text-[#9af8df]/90">{action.ai_explanation}</p>
                </div>
            )}

            {/* Generated Query Preview (collapsed by default) */}
            {action.query_template && (
                <div className="space-y-2">
                    <button
                        type="button"
                        onClick={() => setShowAdvanced(!showAdvanced)}
                        className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
                    >
                        {showAdvanced ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                        {showAdvanced ? 'Hide' : 'Show'} generated query
                    </button>

                    {showAdvanced && (
                        <div className="space-y-2">
                            <Textarea
                                value={action.query_template}
                                onChange={(e) => updateAction({ query_template: e.target.value })}
                                className="min-h-[100px] font-mono text-xs bg-background/50"
                            />
                            <p className="text-xs text-muted-foreground">
                                Advanced: you can edit the query directly if needed.
                            </p>
                        </div>
                    )}
                </div>
            )}

            {/* Result Variable (for query operations) */}
            {action.operation === 'query' && (
                <div className="space-y-2">
                    <Label className="text-sm font-medium">Save results as</Label>
                    <Input
                        value={action.result_variable || ''}
                        onChange={(e) => updateAction({ result_variable: e.target.value })}
                        placeholder="query_result"
                        className="font-mono text-sm bg-background/50"
                    />
                    <p className="text-xs text-muted-foreground">
                        Give a name to the results so you can use them later in the conversation
                    </p>
                </div>
            )}

            {/* Available Variables */}
            <VariableChips variables={availableVariables} label="Available Information" />

            {/* Continue on Error */}
            <div className="flex items-center justify-between p-3 rounded-lg bg-muted/20 border border-border/50">
                <div className="space-y-0.5">
                    <Label className="text-sm font-medium">Continue on Error</Label>
                    <p className="text-xs text-muted-foreground">
                        Keep going even if this step fails
                    </p>
                </div>
                <Switch
                    checked={action.continue_on_error ?? false}
                    onCheckedChange={(checked) => updateAction({ continue_on_error: checked })}
                />
            </div>
        </div>
    );
}
