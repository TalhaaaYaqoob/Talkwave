'use client';

import { MessageSquare, Phone, Variable } from 'lucide-react';

import { TwilioSmsConfig } from '@/components/flow/types';
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

interface TwilioSmsToolConfigProps {
    config: TwilioSmsConfig;
    onChange: (config: TwilioSmsConfig) => void;
}

const DEFAULT_CONFIG: TwilioSmsConfig = {
    enabled: true,
    description: 'Send an SMS message to the customer',
    to_number_source: 'context',
    to_number_variable: 'customer_phone',
    message_template: '',
    use_conversation_context: true,
};

export function TwilioSmsToolConfig({ config, onChange }: TwilioSmsToolConfigProps) {
    const currentConfig = { ...DEFAULT_CONFIG, ...config };

    const updateConfig = (updates: Partial<TwilioSmsConfig>) => {
        onChange({ ...currentConfig, ...updates });
    };

    return (
        <div className="space-y-5">
            {/* Description */}
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <MessageSquare className="w-4 h-4 text-emerald-500" />
                    Tool Description (for AI)
                </Label>
                <Textarea
                    placeholder="Describe when the AI should use this tool..."
                    value={currentConfig.description}
                    onChange={(e) => updateConfig({ description: e.target.value })}
                    className="min-h-[80px] bg-background/50 border-border/50 focus:border-emerald-500/50"
                />
                <p className="text-xs text-muted-foreground">
                    This helps the AI understand when to send an SMS during the conversation
                </p>
            </div>

            {/* Recipient Configuration */}
            <div className="space-y-3 p-4 rounded-lg bg-muted/30 border border-border/50">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <Phone className="w-4 h-4 text-primary" />
                    Recipient Phone Number
                </Label>
                <Select
                    value={currentConfig.to_number_source}
                    onValueChange={(value: 'context' | 'static') =>
                        updateConfig({ to_number_source: value })
                    }
                >
                    <SelectTrigger className="bg-background/50">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="context">
                            <div className="flex items-center gap-2">
                                <Variable className="w-4 h-4" />
                                From Context Variable
                            </div>
                        </SelectItem>
                        <SelectItem value="static">
                            <div className="flex items-center gap-2">
                                <Phone className="w-4 h-4" />
                                Static Number
                            </div>
                        </SelectItem>
                    </SelectContent>
                </Select>

                {currentConfig.to_number_source === 'context' ? (
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Variable Name</Label>
                        <Input
                            placeholder="customer_phone"
                            value={currentConfig.to_number_variable || ''}
                            onChange={(e) => updateConfig({ to_number_variable: e.target.value })}
                            className="font-mono text-sm bg-background/50"
                        />
                        <p className="text-xs text-muted-foreground">
                            Use {'{{variable_name}}'} syntax in your workflow context
                        </p>
                    </div>
                ) : (
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Phone Number</Label>
                        <Input
                            placeholder="+1234567890"
                            value={currentConfig.to_number || ''}
                            onChange={(e) => updateConfig({ to_number: e.target.value })}
                            className="font-mono text-sm bg-background/50"
                        />
                    </div>
                )}
            </div>

            {/* Message Template */}
            <div className="space-y-2">
                <Label className="text-sm font-medium">Message Template</Label>
                <Textarea
                    placeholder="Hi {{customer_name}}, this is a message from our service..."
                    value={currentConfig.message_template}
                    onChange={(e) => updateConfig({ message_template: e.target.value })}
                    className="min-h-[100px] font-mono text-sm bg-background/50 border-border/50"
                />
                <p className="text-xs text-muted-foreground">
                    Use {'{{variable_name}}'} to include dynamic values. Leave empty to let AI compose the message.
                </p>
            </div>

            {/* Context Toggle */}
            <div className="flex items-center justify-between p-3 rounded-lg bg-muted/30 border border-border/50">
                <div className="space-y-0.5">
                    <Label className="text-sm font-medium">Use Conversation Context</Label>
                    <p className="text-xs text-muted-foreground">
                        Allow AI to use conversation history when composing messages
                    </p>
                </div>
                <Switch
                    checked={currentConfig.use_conversation_context}
                    onCheckedChange={(checked) => updateConfig({ use_conversation_context: checked })}
                />
            </div>
        </div>
    );
}

export { DEFAULT_CONFIG as DEFAULT_TWILIO_SMS_CONFIG };

