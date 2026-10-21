'use client';

import { Download, FileSpreadsheet, Plus, RefreshCw, Search, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { GoogleSheetsAction } from '@/components/flow/types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { getBackendUrl } from '@/lib/apiClient';
import { useAuth } from '@/lib/auth';

import { VariableChips } from './VariableChips';

/** Converts a 0-based index into a spreadsheet column letter (A, B, ..., Z, AA, AB, ...). */
function indexToColumnLetter(index: number): string {
    let result = '';
    let n = index;
    while (n >= 0) {
        result = String.fromCharCode((n % 26) + 65) + result;
        n = Math.floor(n / 26) - 1;
    }
    return result;
}

/** Returns the first column letter not already used in the mapping. */
function nextAvailableColumn(usedColumns: string[]): string {
    const used = new Set(usedColumns.map((c) => c.toUpperCase()));
    for (let i = 0; i < 702; i++) {
        const letter = indexToColumnLetter(i);
        if (!used.has(letter)) return letter;
    }
    return '';
}

interface GoogleSheetsActionPanelProps {
    action: GoogleSheetsAction;
    onChange: (action: GoogleSheetsAction) => void;
    availableVariables?: string[];
}

const OPERATION_CONFIG = {
    append: { icon: Plus, label: 'Append Row', description: 'Add a new row to the sheet' },
    update: { icon: RefreshCw, label: 'Update', description: 'Update existing cells' },
    read: { icon: Search, label: 'Read', description: 'Read data from the sheet' },
};

export function GoogleSheetsActionPanel({ action, onChange, availableVariables = [] }: GoogleSheetsActionPanelProps) {
    const [newColumnKey, setNewColumnKey] = useState('');
    const [newColumnValue, setNewColumnValue] = useState('');
    const { getAccessToken } = useAuth();
    const [loadingDefaults, setLoadingDefaults] = useState(false);

    const updateAction = (updates: Partial<GoogleSheetsAction>) => {
        onChange({ ...action, ...updates });
    };

    const loadFromIntegration = useCallback(async () => {
        setLoadingDefaults(true);
        try {
            const token = await getAccessToken();
            const res = await fetch(`${getBackendUrl()}/api/v1/composio/apps/googlesheets/settings`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            if (res.ok) {
                const data = await res.json();
                const s = data.settings || {};
                const updates: Partial<GoogleSheetsAction> = {};
                if (s.default_spreadsheet_id) updates.spreadsheet_id = s.default_spreadsheet_id;
                if (s.default_sheet_name) updates.sheet_name = s.default_sheet_name;
                if (Object.keys(updates).length > 0) onChange({ ...action, ...updates });
            }
        } catch {
            // silently ignore
        } finally {
            setLoadingDefaults(false);
        }
    }, [getAccessToken, action, onChange]);

    useEffect(() => {
        if (!action.spreadsheet_id) {
            loadFromIntegration();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const suggestedColumn = useMemo(
        () => nextAvailableColumn(Object.keys(action.data_mapping)),
        [action.data_mapping]
    );

    const addMapping = () => {
        // Fall back to the next free column letter if the user didn't type one.
        const columnKey = (newColumnKey || suggestedColumn).toUpperCase();
        if (!columnKey) return;
        updateAction({
            data_mapping: {
                ...action.data_mapping,
                [columnKey]: newColumnValue,
            },
        });
        setNewColumnKey('');
        setNewColumnValue('');
    };

    const removeMapping = (key: string) => {
        const newMapping = { ...action.data_mapping };
        delete newMapping[key];
        updateAction({ data_mapping: newMapping });
    };

    return (
        <div className="space-y-4">
            {/* Action Name */}
            <div className="space-y-2">
                <Label className="text-sm font-medium">Action Name</Label>
                <Input
                    value={action.name}
                    onChange={(e) => updateAction({ name: e.target.value })}
                    placeholder="Log call data to sheet"
                    className="bg-background/50"
                />
            </div>

            {/* Operation Type */}
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <FileSpreadsheet className="w-4 h-4 text-green-500" />
                    Operation
                </Label>
                <div className="grid grid-cols-3 gap-2">
                    {(['append', 'update', 'read'] as const).map((op) => {
                        const config = OPERATION_CONFIG[op];
                        const Icon = config.icon;
                        return (
                            <button
                                key={op}
                                type="button"
                                onClick={() => updateAction({ operation: op })}
                                className={`
                                    p-3 rounded-lg border text-left transition-all
                                    ${action.operation === op
                                        ? 'border-green-500/50 bg-green-500/10 ring-1 ring-green-500/30'
                                        : 'border-border/50 bg-background/50 hover:border-border'}
                                `}
                            >
                                <Icon className={`w-4 h-4 mb-1 ${action.operation === op ? 'text-green-500' : 'text-muted-foreground'}`} />
                                <p className="text-sm font-medium">{config.label}</p>
                            </button>
                        );
                    })}
                </div>
            </div>

            {/* Spreadsheet Settings */}
            <div className="space-y-3 p-3 rounded-lg bg-muted/30 border border-border/50">
                <div className="flex items-center justify-between">
                    <Label className="text-sm font-medium">Spreadsheet Settings</Label>
                    <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 text-xs text-muted-foreground hover:text-foreground"
                        onClick={loadFromIntegration}
                        disabled={loadingDefaults}
                    >
                        <Download className="w-3 h-3 mr-1" />
                        {loadingDefaults ? 'Loading...' : 'Load from integration'}
                    </Button>
                </div>
                <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Spreadsheet ID</Label>
                        <Input
                            value={action.spreadsheet_id}
                            onChange={(e) => updateAction({ spreadsheet_id: e.target.value })}
                            placeholder="1BxiMVs0XRA5nF..."
                            className="font-mono text-xs bg-background/50"
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Sheet Name</Label>
                        <Input
                            value={action.sheet_name}
                            onChange={(e) => updateAction({ sheet_name: e.target.value })}
                            placeholder="Sheet1"
                            className="bg-background/50"
                        />
                    </div>
                </div>
                {action.operation !== 'append' && (
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Range (A1 notation)</Label>
                        <Input
                            value={action.range || ''}
                            onChange={(e) => updateAction({ range: e.target.value })}
                            placeholder="A1:Z1000"
                            className="font-mono text-sm bg-background/50"
                        />
                    </div>
                )}
            </div>

            {/* Data Mapping */}
            {action.operation !== 'read' && (
                <div className="space-y-3">
                    <Label className="text-sm font-medium">Column Mapping</Label>

                    {/* Existing mappings */}
                    {Object.entries(action.data_mapping).length > 0 && (
                        <div className="space-y-2">
                            {Object.entries(action.data_mapping).map(([col, val]) => (
                                <div key={col} className="flex items-center gap-2 p-2 rounded bg-background/50 border border-border/50">
                                    <code className="px-2 py-0.5 bg-green-500/10 text-green-600 rounded text-xs font-bold">
                                        {col}
                                    </code>
                                    <span className="text-muted-foreground">→</span>
                                    <code className="flex-1 text-xs font-mono">{val}</code>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        className="h-6 w-6"
                                        onClick={() => removeMapping(col)}
                                    >
                                        <Trash2 className="w-3 h-3" />
                                    </Button>
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Add new mapping */}
                    <div className="flex gap-2 items-end">
                        <div className="space-y-1 flex-1">
                            <Label className="text-xs text-muted-foreground">Column</Label>
                            <Input
                                value={newColumnKey}
                                onChange={(e) => setNewColumnKey(e.target.value.toUpperCase())}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') {
                                        e.preventDefault();
                                        addMapping();
                                    }
                                }}
                                placeholder={suggestedColumn || 'A'}
                                className="font-mono text-sm bg-background/50"
                            />
                        </div>
                        <div className="space-y-1 flex-[2]">
                            <Label className="text-xs text-muted-foreground">Value</Label>
                            <Input
                                value={newColumnValue}
                                onChange={(e) => setNewColumnValue(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') {
                                        e.preventDefault();
                                        addMapping();
                                    }
                                }}
                                placeholder="{{customer_name}}"
                                className="font-mono text-sm bg-background/50"
                            />
                        </div>
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={addMapping}
                            disabled={!newColumnValue.trim() && !newColumnKey.trim()}
                        >
                            <Plus className="w-4 h-4" />
                        </Button>
                    </div>
                    <p className="text-xs text-muted-foreground">
                        Focus the Value field, then click a variable below to insert it.
                        Leave Column blank to auto-use the next column ({suggestedColumn || 'A'}).
                    </p>
                </div>
            )}

            {/* Available Variables */}
            <VariableChips variables={availableVariables} />

            {/* Continue on Error */}
            <div className="flex items-center justify-between p-3 rounded-lg bg-muted/20 border border-border/50">
                <div className="space-y-0.5">
                    <Label className="text-sm font-medium">Continue on Error</Label>
                    <p className="text-xs text-muted-foreground">
                        Continue to next action even if this fails
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

