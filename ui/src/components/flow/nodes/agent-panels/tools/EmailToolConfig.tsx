'use client';

import { AtSign, FileText, Mail, Variable } from 'lucide-react';

import { EmailConfig } from '@/components/flow/types';
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

interface EmailToolConfigProps {
    config: EmailConfig;
    onChange: (config: EmailConfig) => void;
}

const DEFAULT_CONFIG: EmailConfig = {
    enabled: true,
    description: 'Send an email to the customer',
    to_email_source: 'context',
    to_email_variable: 'customer_email',
    subject_template: '',
    body_template: '',
    use_html: false,
};

export function EmailToolConfig({ config, onChange }: EmailToolConfigProps) {
    const currentConfig = { ...DEFAULT_CONFIG, ...config };

    const updateConfig = (updates: Partial<EmailConfig>) => {
        onChange({ ...currentConfig, ...updates });
    };

    return (
        <div className="space-y-5">
            {/* Description */}
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <Mail className="w-4 h-4 text-red-500" />
                    Tool Description (for AI)
                </Label>
                <Textarea
                    placeholder="Describe when the AI should send an email..."
                    value={currentConfig.description}
                    onChange={(e) => updateConfig({ description: e.target.value })}
                    className="min-h-[80px] bg-background/50 border-border/50 focus:border-red-500/50"
                />
            </div>

            {/* Recipient Configuration */}
            <div className="space-y-3 p-4 rounded-lg bg-muted/30 border border-border/50">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <AtSign className="w-4 h-4 text-primary" />
                    Recipient Email
                </Label>
                <Select
                    value={currentConfig.to_email_source}
                    onValueChange={(value: 'context' | 'static') =>
                        updateConfig({ to_email_source: value })
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
                                <AtSign className="w-4 h-4" />
                                Static Email
                            </div>
                        </SelectItem>
                    </SelectContent>
                </Select>

                {currentConfig.to_email_source === 'context' ? (
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Variable Name</Label>
                        <Input
                            placeholder="customer_email"
                            value={currentConfig.to_email_variable || ''}
                            onChange={(e) => updateConfig({ to_email_variable: e.target.value })}
                            className="font-mono text-sm bg-background/50"
                        />
                    </div>
                ) : (
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Email Address</Label>
                        <Input
                            placeholder="customer@example.com"
                            value={currentConfig.to_email || ''}
                            onChange={(e) => updateConfig({ to_email: e.target.value })}
                            className="bg-background/50"
                        />
                    </div>
                )}
            </div>

            {/* Subject */}
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <FileText className="w-4 h-4 text-orange-500" />
                    Subject Line
                </Label>
                <Input
                    placeholder="Order Confirmation - {{order_id}}"
                    value={currentConfig.subject_template}
                    onChange={(e) => updateConfig({ subject_template: e.target.value })}
                    className="bg-background/50"
                />
                <p className="text-xs text-muted-foreground">
                    Use {'{{variable}}'} for dynamic values. Leave empty for AI to generate.
                </p>
            </div>

            {/* Body Template */}
            <div className="space-y-2">
                <Label className="text-sm font-medium">Email Body</Label>
                <Textarea
                    placeholder={currentConfig.use_html
                        ? "<html><body><h1>Hello {{customer_name}}</h1>...</body></html>"
                        : "Hello {{customer_name}},\n\nThank you for contacting us..."
                    }
                    value={currentConfig.body_template}
                    onChange={(e) => updateConfig({ body_template: e.target.value })}
                    className="min-h-[150px] font-mono text-sm bg-background/50"
                />
                <p className="text-xs text-muted-foreground">
                    Leave empty to let AI compose the email based on conversation context
                </p>
            </div>

            {/* HTML Toggle */}
            <div className="flex items-center justify-between p-3 rounded-lg bg-muted/30 border border-border/50">
                <div className="space-y-0.5">
                    <Label className="text-sm font-medium">HTML Email</Label>
                    <p className="text-xs text-muted-foreground">
                        Enable rich HTML formatting in the email body
                    </p>
                </div>
                <Switch
                    checked={currentConfig.use_html}
                    onCheckedChange={(checked) => updateConfig({ use_html: checked })}
                />
            </div>

            {/* Info Box */}
            <div className="p-3 rounded-lg bg-primary/5 border border-primary/20">
                <p className="text-xs text-primary">
                    <strong>Note:</strong> Requires Gmail or email integration to be connected in the Integrations page.
                </p>
            </div>
        </div>
    );
}

export { DEFAULT_CONFIG as DEFAULT_EMAIL_CONFIG };

