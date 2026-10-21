'use client';

import { Calendar, Clock, Globe, MapPin, Users } from 'lucide-react';

import { ScheduleMeetingAction } from '@/components/flow/types';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';

import { VariableChips } from './VariableChips';

interface ScheduleMeetingActionPanelProps {
    action: ScheduleMeetingAction;
    onChange: (action: ScheduleMeetingAction) => void;
    availableVariables?: string[];
}

const TIMEZONE_OPTIONS = [
    'UTC',
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Los_Angeles',
    'America/Toronto',
    'Europe/London',
    'Europe/Paris',
    'Europe/Berlin',
    'Asia/Dubai',
    'Asia/Kolkata',
    'Asia/Shanghai',
    'Asia/Tokyo',
    'Australia/Sydney',
    'Pacific/Auckland',
];

export function ScheduleMeetingActionPanel({ action, onChange, availableVariables = [] }: ScheduleMeetingActionPanelProps) {
    const updateAction = (updates: Partial<ScheduleMeetingAction>) => {
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
                    placeholder="Schedule a meeting"
                    className="bg-background/50"
                />
            </div>

            {/* Event Title */}
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <Calendar className="w-4 h-4 text-primary" />
                    Event Title
                </Label>
                <Input
                    value={action.event_title}
                    onChange={(e) => updateAction({ event_title: e.target.value })}
                    placeholder="Meeting with {{first_name}}"
                    className="bg-background/50"
                />
                <p className="text-xs text-muted-foreground">
                    Use {'{{variable}}'} to insert extracted values
                </p>
            </div>

            {/* Attendee Email */}
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <Users className="w-4 h-4 text-primary" />
                    Attendee Email
                </Label>
                <Input
                    value={action.attendee_email}
                    onChange={(e) => updateAction({ attendee_email: e.target.value })}
                    placeholder="{{email}} or name@example.com"
                    className="bg-background/50"
                />
            </div>

            {/* Date & Time */}
            <div className="space-y-3 p-3 rounded-lg bg-muted/30 border border-border/50">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <Clock className="w-4 h-4 text-primary" />
                    Date & Time
                </Label>
                <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Start Time</Label>
                        <Input
                            value={action.start_time}
                            onChange={(e) => updateAction({ start_time: e.target.value })}
                            placeholder="{{meeting_date}} or 2025-03-15T10:00:00"
                            className="font-mono text-xs bg-background/50"
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">End Time</Label>
                        <Input
                            value={action.end_time}
                            onChange={(e) => updateAction({ end_time: e.target.value })}
                            placeholder="{{meeting_end}} or 2025-03-15T11:00:00"
                            className="font-mono text-xs bg-background/50"
                        />
                    </div>
                </div>
                <p className="text-xs text-muted-foreground">
                    Use ISO 8601 format (YYYY-MM-DDTHH:MM:SS) or {'{{variable}}'} from the conversation
                </p>
            </div>

            {/* Timezone */}
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <Globe className="w-4 h-4 text-primary" />
                    Timezone
                </Label>
                <select
                    value={action.timezone || 'UTC'}
                    onChange={(e) => updateAction({ timezone: e.target.value })}
                    className="w-full rounded-md border border-input bg-background/50 px-3 py-2 text-sm"
                >
                    {TIMEZONE_OPTIONS.map((tz) => (
                        <option key={tz} value={tz}>{tz}</option>
                    ))}
                </select>
            </div>

            {/* Location */}
            <div className="space-y-2">
                <Label className="text-sm font-medium flex items-center gap-2">
                    <MapPin className="w-4 h-4 text-primary" />
                    Location
                    <span className="text-xs text-muted-foreground font-normal">(optional)</span>
                </Label>
                <Input
                    value={action.location || ''}
                    onChange={(e) => updateAction({ location: e.target.value })}
                    placeholder="https://meet.google.com/... or office address"
                    className="bg-background/50"
                />
            </div>

            {/* Description */}
            <div className="space-y-2">
                <Label className="text-sm font-medium">
                    Description
                    <span className="text-xs text-muted-foreground font-normal ml-1">(optional)</span>
                </Label>
                <textarea
                    value={action.description || ''}
                    onChange={(e) => updateAction({ description: e.target.value })}
                    placeholder="Meeting notes or agenda. Use {{variable}} for dynamic content."
                    className="w-full rounded-md border border-input bg-background/50 px-3 py-2 text-sm min-h-[80px] resize-y"
                    rows={3}
                />
            </div>

            {/* Send Notifications */}
            <div className="flex items-center justify-between p-3 rounded-lg bg-muted/20 border border-border/50">
                <div className="space-y-0.5">
                    <Label className="text-sm font-medium">Send Notifications</Label>
                    <p className="text-xs text-muted-foreground">
                        Send calendar invite to the attendee
                    </p>
                </div>
                <Switch
                    checked={action.send_notifications ?? true}
                    onCheckedChange={(checked) => updateAction({ send_notifications: checked })}
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
