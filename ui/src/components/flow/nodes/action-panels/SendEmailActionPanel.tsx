'use client';

import { AtSign, FileText, Mail, Sparkles } from 'lucide-react';

import { Spinner } from '@/components/ui/ai-loader';
import { useState } from 'react';

import { SendEmailAction } from '@/components/flow/types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useUserConfig } from '@/context/UserConfigContext';
import { getBackendUrl } from '@/lib/apiClient';

import { VariableChips } from './VariableChips';

interface SendEmailActionPanelProps {
    action: SendEmailAction;
    onChange: (action: SendEmailAction) => void;
    availableVariables?: string[];
}

export function SendEmailActionPanel({ action, onChange, availableVariables = [] }: SendEmailActionPanelProps) {
    const { accessToken } = useUserConfig();
    const [aiDescription, setAiDescription] = useState('');
    const [isGenerating, setIsGenerating] = useState(false);
    const [aiExplanation, setAiExplanation] = useState('');

    const updateAction = (updates: Partial<SendEmailAction>) => {
        onChange({ ...action, ...updates });
    };

    const handleAIGenerate = async () => {
        if (!aiDescription.trim() || !accessToken) return;
        setIsGenerating(true);
        try {
            const baseUrl = getBackendUrl();
            const res = await fetch(`${baseUrl}/api/v1/workflow/ai/action-help`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    action_type: 'email',
                    description: aiDescription,
                    action_data: { to_email: action.to_email, subject: action.subject },
                    available_variables: availableVariables,
                }),
            });
            if (!res.ok) throw new Error('Failed');
            const data = await res.json();
            if (data.suggestion?.content) {
                const c = data.suggestion.content;
                if (c.subject) updateAction({ subject: c.subject });
                if (c.body) updateAction({ body: c.body });
                if (c.is_html !== undefined) updateAction({ is_html: c.is_html });
            }
            if (data.suggestion?.explanation) setAiExplanation(data.suggestion.explanation);
        } catch (err) {
            console.error('AI generation failed:', err);
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
                    placeholder="Send confirmation email"
                    className="bg-background/50"
                />
            </div>

            {/* To Email */}
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <AtSign className="w-4 h-4 text-primary" />
                    To Email
                </Label>
                <Input
                    value={action.to_email}
                    onChange={(e) => updateAction({ to_email: e.target.value })}
                    placeholder="{{customer_email}} or email@example.com"
                    className="font-mono text-sm bg-background/50"
                />
                <p className="text-xs text-muted-foreground">
                    Use a variable like {'{{customer_email}}'} to send to the caller&apos;s email
                </p>
            </div>

            {/* AI Helper */}
            <div className="space-y-3 p-4 rounded-xl border border-emerald-500/20 bg-emerald-500/5">
                <div className="flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-emerald-400" />
                    <Label className="text-sm font-semibold text-emerald-400">Describe the email</Label>
                </div>
                <Textarea
                    value={aiDescription}
                    onChange={(e) => setAiDescription(e.target.value)}
                    placeholder="e.g., Send a booking confirmation with the customer's name, date, and time"
                    className="min-h-[60px] bg-background/50 resize-none text-sm"
                />
                <p className="text-xs text-muted-foreground">
                    Tell us what the email should say and AI will write the subject and body for you.
                </p>
                <Button
                    onClick={handleAIGenerate}
                    disabled={isGenerating || !aiDescription.trim()}
                    size="sm"
                    className="w-full gap-2 bg-emerald-600 hover:bg-emerald-700 text-white"
                >
                    {isGenerating ? (
                        <><Spinner size="sm" /> Generating...</>
                    ) : (
                        <><Sparkles className="w-3 h-3" /> Generate with AI</>
                    )}
                </Button>
            </div>

            {/* AI Explanation */}
            {aiExplanation && (
                <div className="p-3 rounded-lg bg-primary/5 border border-primary/20">
                    <p className="text-xs font-semibold text-primary mb-1">What this does:</p>
                    <p className="text-sm text-[#9af8df]/90">{aiExplanation}</p>
                </div>
            )}

            {/* Subject */}
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <FileText className="w-4 h-4 text-orange-500" />
                    Subject Line
                </Label>
                <Input
                    value={action.subject}
                    onChange={(e) => updateAction({ subject: e.target.value })}
                    placeholder="Your Appointment Confirmation"
                    className="bg-background/50"
                />
            </div>

            {/* Body */}
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <Mail className="w-4 h-4 text-red-500" />
                    Email Body
                </Label>
                <Textarea
                    value={action.body}
                    onChange={(e) => updateAction({ body: e.target.value })}
                    placeholder={action.is_html
                        ? "<h1>Hello {{customer_name}}</h1><p>Your appointment is confirmed.</p>"
                        : "Hello {{customer_name}},\n\nYour appointment has been confirmed.\n\nThank you!"
                    }
                    className="min-h-[150px] font-mono text-sm bg-background/50"
                />
            </div>

            {/* HTML Toggle */}
            <div className="flex items-center justify-between p-3 rounded-lg bg-muted/20 border border-border/50">
                <div className="space-y-0.5">
                    <Label className="text-sm font-medium">Rich Formatting (HTML)</Label>
                    <p className="text-xs text-muted-foreground">
                        Enable for styled emails with bold, colors, etc.
                    </p>
                </div>
                <Switch
                    checked={action.is_html ?? false}
                    onCheckedChange={(checked) => updateAction({ is_html: checked })}
                />
            </div>

            {/* Available Variables */}
            <VariableChips variables={availableVariables} label="Available Information" />

            {/* Continue on Error */}
            <div className="flex items-center justify-between p-3 rounded-lg bg-muted/20 border border-border/50">
                <div className="space-y-0.5">
                    <Label className="text-sm font-medium">Continue on Error</Label>
                    <p className="text-xs text-muted-foreground">Keep going even if this step fails</p>
                </div>
                <Switch
                    checked={action.continue_on_error ?? false}
                    onCheckedChange={(checked) => updateAction({ continue_on_error: checked })}
                />
            </div>
        </div>
    );
}
