'use client';

import { MessageSquare, Phone } from 'lucide-react';

import { SendSmsAction } from '@/components/flow/types';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';

import { VariableChips } from './VariableChips';

interface SendSmsActionPanelProps {
    action: SendSmsAction;
    onChange: (action: SendSmsAction) => void;
    availableVariables?: string[];
}

export function SendSmsActionPanel({ action, onChange, availableVariables = [] }: SendSmsActionPanelProps) {
    const updateAction = (updates: Partial<SendSmsAction>) => {
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
                    placeholder="Send confirmation SMS"
                    className="bg-background/50"
                />
            </div>

            {/* To Number */}
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <Phone className="w-4 h-4 text-primary" />
                    To Phone Number
                </Label>
                <Input
                    value={action.to_number}
                    onChange={(e) => updateAction({ to_number: e.target.value })}
                    placeholder="{{customer_phone}} or +1234567890"
                    className="font-mono text-sm bg-background/50"
                />
                <p className="text-xs text-muted-foreground">
                    Use {'{{variable_name}}'} to insert extracted values
                </p>
            </div>

            {/* Message */}
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <MessageSquare className="w-4 h-4 text-emerald-500" />
                    Message
                </Label>
                <Textarea
                    value={action.message}
                    onChange={(e) => updateAction({ message: e.target.value })}
                    placeholder="Hi {{customer_name}}, your order #{{order_id}} has been confirmed..."
                    className="min-h-[120px] font-mono text-sm bg-background/50"
                />
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

