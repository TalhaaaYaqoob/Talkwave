'use client';

import { Hash, MessageSquare } from 'lucide-react';

import { SendSlackAction } from '@/components/flow/types';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';

import { VariableChips } from './VariableChips';

interface SendSlackActionPanelProps {
    action: SendSlackAction;
    onChange: (action: SendSlackAction) => void;
    availableVariables?: string[];
}

export function SendSlackActionPanel({ action, onChange, availableVariables = [] }: SendSlackActionPanelProps) {
    const updateAction = (updates: Partial<SendSlackAction>) => {
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
                    placeholder="Post to Slack"
                    className="bg-background/50"
                />
            </div>

            {/* Channel */}
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <Hash className="w-4 h-4 text-purple-400" />
                    Channel
                </Label>
                <Input
                    value={action.channel}
                    onChange={(e) => updateAction({ channel: e.target.value })}
                    placeholder="#general or C0123456789"
                    className="font-mono text-sm bg-background/50"
                />
                <p className="text-xs text-muted-foreground">
                    Enter channel name (with #) or channel ID
                </p>
            </div>

            {/* Message */}
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <MessageSquare className="w-4 h-4 text-purple-400" />
                    Message
                </Label>
                <Textarea
                    value={action.message}
                    onChange={(e) => updateAction({ message: e.target.value })}
                    placeholder="New appointment booked:\n• Customer: {{customer_name}}\n• Date: {{date}}\n• Time: {{time}}"
                    className="min-h-[120px] font-mono text-sm bg-background/50"
                />
                <p className="text-xs text-muted-foreground">
                    Supports Slack mrkdwn formatting
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

