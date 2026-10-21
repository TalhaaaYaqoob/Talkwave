'use client';

import { Variable } from 'lucide-react';

import { SetVariableAction } from '@/components/flow/types';
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

import { VariableChips } from './VariableChips';

interface SetVariableActionPanelProps {
    action: SetVariableAction;
    onChange: (action: SetVariableAction) => void;
    availableVariables?: string[];
}

export function SetVariableActionPanel({ action, onChange, availableVariables = [] }: SetVariableActionPanelProps) {
    const updateAction = (updates: Partial<SetVariableAction>) => {
        onChange({ ...action, ...updates });
    };

    return (
        <div className="space-y-4">
            {/* Action Name */}
            <div className="space-y-2">
                <Label className="text-sm font-medium">Action Name</Label>
                <Input
                    value={action.name}
                    onChange={(e) => updateAction({ name: e.target.value })}
                    placeholder="Set status variable"
                    className="bg-background/50"
                />
            </div>

            {/* Variable Name */}
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <Variable className="w-4 h-4 text-cyan-500" />
                    Variable Name
                </Label>
                <Input
                    value={action.variable_name}
                    onChange={(e) => updateAction({ variable_name: e.target.value.replace(/[^a-zA-Z0-9_]/g, '_') })}
                    placeholder="call_status"
                    className="font-mono text-sm bg-background/50"
                />
            </div>

            {/* Value Type */}
            <div className="space-y-2">
                <Label className="text-sm font-medium">Value Type</Label>
                <Select
                    value={action.value_type}
                    onValueChange={(value: SetVariableAction['value_type']) => updateAction({ value_type: value })}
                >
                    <SelectTrigger className="bg-background/50">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="string">String</SelectItem>
                        <SelectItem value="number">Number</SelectItem>
                        <SelectItem value="boolean">Boolean</SelectItem>
                        <SelectItem value="json">JSON Object</SelectItem>
                    </SelectContent>
                </Select>
            </div>

            {/* Value */}
            <div className="space-y-2">
                <Label className="text-sm font-medium">Value</Label>
                {action.value_type === 'json' ? (
                    <Textarea
                        value={action.value}
                        onChange={(e) => updateAction({ value: e.target.value })}
                        placeholder={`{
  "status": "completed",
  "customer": "{{customer_name}}"
}`}
                        className="min-h-[100px] font-mono text-xs bg-background/50"
                    />
                ) : action.value_type === 'boolean' ? (
                    <Select
                        value={action.value}
                        onValueChange={(value) => updateAction({ value })}
                    >
                        <SelectTrigger className="bg-background/50">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="true">true</SelectItem>
                            <SelectItem value="false">false</SelectItem>
                        </SelectContent>
                    </Select>
                ) : (
                    <Input
                        value={action.value}
                        onChange={(e) => updateAction({ value: e.target.value })}
                        placeholder={action.value_type === 'number' ? '123' : 'completed'}
                        type={action.value_type === 'number' ? 'number' : 'text'}
                        className="font-mono text-sm bg-background/50"
                    />
                )}
                <p className="text-xs text-muted-foreground">
                    Use {'{{variable_name}}'} to reference other variables
                </p>
            </div>

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

