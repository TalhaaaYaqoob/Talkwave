'use client';

import { useCallback, useEffect, useState } from 'react';
import { Download, FileSpreadsheet, Plus, RefreshCw, Search } from 'lucide-react';

import { GoogleSheetsConfig } from '@/components/flow/types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { getBackendUrl } from '@/lib/apiClient';
import { useAuth } from '@/lib/auth';

interface GoogleSheetsToolConfigProps {
    config: GoogleSheetsConfig;
    onChange: (config: GoogleSheetsConfig) => void;
}

const DEFAULT_CONFIG: GoogleSheetsConfig = {
    enabled: true,
    description: 'Access and manage data in Google Sheets',
    operation: 'read',
    spreadsheet_id: '',
    sheet_name: 'Sheet1',
    range: 'A1:Z1000',
    data_mapping: {},
};

const OPERATION_ICONS = {
    read: <Search className="w-4 h-4" />,
    append: <Plus className="w-4 h-4" />,
    update: <RefreshCw className="w-4 h-4" />,
};

const OPERATION_DESCRIPTIONS = {
    read: 'Search and retrieve data from the spreadsheet',
    append: 'Add new rows to the spreadsheet',
    update: 'Update existing data in the spreadsheet',
};

export function GoogleSheetsToolConfig({ config, onChange }: GoogleSheetsToolConfigProps) {
    const currentConfig = { ...DEFAULT_CONFIG, ...config };
    const { getAccessToken } = useAuth();
    const [loadingDefaults, setLoadingDefaults] = useState(false);

    const updateConfig = (updates: Partial<GoogleSheetsConfig>) => {
        onChange({ ...currentConfig, ...updates });
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
                const updates: Partial<GoogleSheetsConfig> = {};
                if (s.default_spreadsheet_id && !currentConfig.spreadsheet_id) {
                    updates.spreadsheet_id = s.default_spreadsheet_id;
                }
                if (s.default_sheet_name && currentConfig.sheet_name === 'Sheet1') {
                    updates.sheet_name = s.default_sheet_name;
                }
                if (Object.keys(updates).length > 0) {
                    onChange({ ...currentConfig, ...updates });
                }
            }
        } catch {
            // silently ignore
        } finally {
            setLoadingDefaults(false);
        }
    }, [getAccessToken, currentConfig, onChange]);

    useEffect(() => {
        if (!currentConfig.spreadsheet_id) {
            loadFromIntegration();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    return (
        <div className="space-y-5">
            {/* Description */}
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <FileSpreadsheet className="w-4 h-4 text-green-500" />
                    Tool Description (for AI)
                </Label>
                <Textarea
                    placeholder="Describe what data this tool accesses and when to use it..."
                    value={currentConfig.description}
                    onChange={(e) => updateConfig({ description: e.target.value })}
                    className="min-h-[80px] bg-background/50 border-border/50 focus:border-green-500/50"
                />
            </div>

            {/* Operation Type */}
            <div className="space-y-3">
                <Label className="text-sm font-medium">Operation</Label>
                <div className="grid grid-cols-3 gap-2">
                    {(['read', 'append', 'update'] as const).map((op) => (
                        <button
                            key={op}
                            type="button"
                            onClick={() => updateConfig({ operation: op })}
                            className={`
                                p-3 rounded-lg border text-left transition-all
                                ${currentConfig.operation === op
                                    ? 'border-green-500/50 bg-green-500/10 ring-1 ring-green-500/30'
                                    : 'border-border/50 bg-background/50 hover:border-border'}
                            `}
                        >
                            <div className="flex items-center gap-2 mb-1">
                                <span className={currentConfig.operation === op ? 'text-green-500' : 'text-muted-foreground'}>
                                    {OPERATION_ICONS[op]}
                                </span>
                                <span className="font-medium capitalize text-sm">{op}</span>
                            </div>
                            <p className="text-xs text-muted-foreground">
                                {OPERATION_DESCRIPTIONS[op]}
                            </p>
                        </button>
                    ))}
                </div>
            </div>

            {/* Spreadsheet Configuration */}
            <div className="space-y-4 p-4 rounded-lg bg-muted/30 border border-border/50">
                <div className="flex items-center justify-between">
                    <h4 className="text-sm font-medium text-muted-foreground">Spreadsheet Settings</h4>
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

                <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Spreadsheet ID</Label>
                        <Input
                            placeholder="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
                            value={currentConfig.spreadsheet_id || ''}
                            onChange={(e) => updateConfig({ spreadsheet_id: e.target.value })}
                            className="font-mono text-xs bg-background/50"
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Sheet Name</Label>
                        <Input
                            placeholder="Sheet1"
                            value={currentConfig.sheet_name || ''}
                            onChange={(e) => updateConfig({ sheet_name: e.target.value })}
                            className="bg-background/50"
                        />
                    </div>
                </div>

                <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">Range (A1 notation)</Label>
                    <Input
                        placeholder="A1:Z1000"
                        value={currentConfig.range || ''}
                        onChange={(e) => updateConfig({ range: e.target.value })}
                        className="font-mono text-sm bg-background/50"
                    />
                    <p className="text-xs text-muted-foreground">
                        e.g., A1:D100, Sheet1!A:D, or named range
                    </p>
                </div>
            </div>

            {/* Data Mapping (for append/update operations) */}
            {(currentConfig.operation === 'append' || currentConfig.operation === 'update') && (
                <div className="space-y-3 p-4 rounded-lg bg-muted/30 border border-border/50">
                    <Label className="text-sm font-medium">Column Mapping</Label>
                    <Textarea
                        placeholder={`{
  "A": "{{customer_name}}",
  "B": "{{phone}}",
  "C": "{{status}}"
}`}
                        value={JSON.stringify(currentConfig.data_mapping || {}, null, 2)}
                        onChange={(e) => {
                            try {
                                updateConfig({ data_mapping: JSON.parse(e.target.value) });
                            } catch {
                                // Invalid JSON, ignore
                            }
                        }}
                        className="font-mono text-xs min-h-[100px] bg-background/50"
                    />
                    <p className="text-xs text-muted-foreground">
                        Map column letters to context variables using {'{{variable_name}}'} syntax
                    </p>
                </div>
            )}

            {/* Info Box */}
            <div className="p-3 rounded-lg bg-primary/5 border border-primary/20">
                <p className="text-xs text-primary">
                    <strong>Tip:</strong> Set default spreadsheet &amp; sheet in <strong>Integrations &rarr; Google Sheets &rarr; Configure</strong> to auto-fill these fields.
                </p>
            </div>
        </div>
    );
}

export { DEFAULT_CONFIG as DEFAULT_GOOGLE_SHEETS_CONFIG };

