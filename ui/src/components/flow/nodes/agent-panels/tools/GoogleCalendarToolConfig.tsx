'use client';

import { Calendar } from 'lucide-react';

import { GoogleCalendarConfig } from '@/components/flow/types';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';

interface GoogleCalendarToolConfigProps {
    config: GoogleCalendarConfig;
    onChange: (config: GoogleCalendarConfig) => void;
}

const DEFAULT_CONFIG: GoogleCalendarConfig = {
    enabled: true,
    description: 'Create and find events on Google Calendar',
};

export function GoogleCalendarToolConfig({ config, onChange }: GoogleCalendarToolConfigProps) {
    const currentConfig = { ...DEFAULT_CONFIG, ...config };

    return (
        <div className="space-y-5">
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <Calendar className="w-4 h-4 text-primary" />
                    Tool Description (for AI)
                </Label>
                <Textarea
                    placeholder="Describe when the AI should use Google Calendar, e.g. 'Schedule meetings when the caller requests an appointment'"
                    value={currentConfig.description}
                    onChange={(e) => onChange({ ...currentConfig, description: e.target.value })}
                    className="min-h-[80px] bg-background/50 border-border/50 focus:border-primary/50"
                />
            </div>

            <div className="p-3 rounded-lg bg-primary/5 border border-primary/20 space-y-2">
                <p className="text-xs text-primary">
                    <strong>Available actions:</strong> The AI agent will be able to <strong>create events</strong> and
                    <strong> find events</strong> on Google Calendar during the conversation.
                </p>
                <p className="text-xs text-primary">
                    <strong>Tip:</strong> Make sure Google Calendar is connected in{' '}
                    <strong>Integrations</strong> before using this tool.
                </p>
            </div>
        </div>
    );
}

export { DEFAULT_CONFIG as DEFAULT_GOOGLE_CALENDAR_CONFIG };
