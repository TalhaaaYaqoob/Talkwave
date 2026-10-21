"use client";

import { format } from 'date-fns';
import { ArrowLeft, CalendarIcon, Clock } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { createCampaignApiV1CampaignCreatePost, getWorkflowsSummaryApiV1WorkflowSummaryGet } from '@/client/sdk.gen';
import type { WorkflowSummaryResponse } from '@/client/types.gen';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import { useAuth } from '@/lib/auth';

import CsvUploadSelector from '../CsvUploadSelector';
import GoogleSheetSelector from '../GoogleSheetSelector';

const COMMON_TIMEZONES = [
    "UTC",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Anchorage",
    "Pacific/Honolulu",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Asia/Qatar",
    "Asia/Dubai",
    "Asia/Riyadh",
    "Asia/Kolkata",
    "Asia/Shanghai",
    "Asia/Tokyo",
    "Australia/Sydney",
];

const HOURS = Array.from({ length: 12 }, (_, i) => i + 1);
const MINUTES = Array.from({ length: 12 }, (_, i) => i * 5);

function pad(n: number): string {
    return n.toString().padStart(2, '0');
}

function parseTimeToComponents(time: string): { hour: string; minute: string; period: 'AM' | 'PM' } {
    if (!time) return { hour: '9', minute: '0', period: 'AM' };
    const [h, m] = time.split(':').map(Number);
    const period: 'AM' | 'PM' = h >= 12 ? 'PM' : 'AM';
    const hour = h === 0 ? '12' : h > 12 ? String(h - 12) : String(h);
    return { hour, minute: String(m), period };
}

function componentsTo24h(hour: string, minute: string, period: 'AM' | 'PM'): string {
    let h = parseInt(hour);
    if (period === 'AM' && h === 12) h = 0;
    if (period === 'PM' && h !== 12) h += 12;
    return `${pad(h)}:${pad(parseInt(minute))}`;
}

function TimePicker({ value, onChange, label }: { value: string; onChange: (val: string) => void; label: string }) {
    const { hour, minute, period } = parseTimeToComponents(value);

    const handleChange = (newHour?: string, newMinute?: string, newPeriod?: 'AM' | 'PM') => {
        const h = newHour ?? hour;
        const m = newMinute ?? minute;
        const p = newPeriod ?? period;
        onChange(componentsTo24h(h, m, p));
    };

    return (
        <div className="space-y-1.5">
            <Label className="text-xs">{label}</Label>
            <div className="flex items-center gap-1.5">
                <Select value={hour} onValueChange={(h) => handleChange(h, undefined, undefined)}>
                    <SelectTrigger className="w-[68px] h-9">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        {HOURS.map((h) => (
                            <SelectItem key={h} value={String(h)}>{h}</SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                <span className="text-muted-foreground font-medium">:</span>
                <Select value={String(parseInt(minute))} onValueChange={(m) => handleChange(undefined, m, undefined)}>
                    <SelectTrigger className="w-[68px] h-9">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        {MINUTES.map((m) => (
                            <SelectItem key={m} value={String(m)}>{pad(m)}</SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                <Select value={period} onValueChange={(p) => handleChange(undefined, undefined, p as 'AM' | 'PM')}>
                    <SelectTrigger className="w-[68px] h-9">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="AM">AM</SelectItem>
                        <SelectItem value="PM">PM</SelectItem>
                    </SelectContent>
                </Select>
            </div>
        </div>
    );
}

export default function NewCampaignPage() {
    const { user, getAccessToken, redirectToLogin, loading } = useAuth();
    const router = useRouter();

    // Form state
    const [campaignName, setCampaignName] = useState('');
    const [selectedWorkflowId, setSelectedWorkflowId] = useState<string>('');
    const [sourceType, setSourceType] = useState<'google-sheet' | 'csv'>('csv');
    const [sourceId, setSourceId] = useState('');
    const [selectedFileName, setSelectedFileName] = useState('');
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [userAccessToken, setUserAccessToken] = useState<string>('');

    // Scheduling state
    const [scheduledDate, setScheduledDate] = useState<Date | undefined>(undefined);
    const [scheduledTime, setScheduledTime] = useState('09:00');
    const [calendarOpen, setCalendarOpen] = useState(false);

    // Calling window state
    const [callingWindowStart, setCallingWindowStart] = useState('');
    const [callingWindowEnd, setCallingWindowEnd] = useState('');
    const [callingWindowTimezone, setCallingWindowTimezone] = useState('UTC');

    // Workflows state
    const [workflows, setWorkflows] = useState<WorkflowSummaryResponse[]>([]);
    const [isLoadingWorkflows, setIsLoadingWorkflows] = useState(true);

    const detectedTimezone = useMemo(() => {
        try {
            return Intl.DateTimeFormat().resolvedOptions().timeZone;
        } catch {
            return "UTC";
        }
    }, []);

    useEffect(() => {
        if (detectedTimezone && COMMON_TIMEZONES.includes(detectedTimezone)) {
            setCallingWindowTimezone(detectedTimezone);
        }
    }, [detectedTimezone]);

    useEffect(() => {
        if (!loading && !user) {
            redirectToLogin();
        }
    }, [loading, user, redirectToLogin]);

    const fetchWorkflows = useCallback(async () => {
        if (!user) return;
        try {
            const accessToken = await getAccessToken();
            setUserAccessToken(accessToken);
            const response = await getWorkflowsSummaryApiV1WorkflowSummaryGet({
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                }
            });

            if (response.data) {
                setWorkflows(response.data.filter(w => w.call_type === 'OUTBOUND'));
            }
        } catch (error) {
            console.error('Failed to fetch workflows:', error);
            toast.error('Failed to load workflows');
        } finally {
            setIsLoadingWorkflows(false);
        }
    }, [user, getAccessToken]);

    useEffect(() => {
        if (user) {
            fetchWorkflows();
        }
    }, [fetchWorkflows, user]);

    const buildScheduledIso = (): string | undefined => {
        if (!scheduledDate) return undefined;
        const [h, m] = scheduledTime.split(':').map(Number);
        const tz = callingWindowTimezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

        const year = scheduledDate.getFullYear();
        const mon = scheduledDate.getMonth();
        const day = scheduledDate.getDate();

        const refUtcMs = Date.UTC(year, mon, day, h, m, 0);
        const formatter = new Intl.DateTimeFormat('en-US', {
            timeZone: tz,
            year: 'numeric', month: 'numeric', day: 'numeric',
            hour: 'numeric', minute: 'numeric', second: 'numeric',
            hour12: false,
        });
        const parts = formatter.formatToParts(new Date(refUtcMs));
        const g = (t: string) => parseInt(parts.find(p => p.type === t)?.value || '0');
        const hr = g('hour') === 24 ? 0 : g('hour');
        const tzDisplayMs = Date.UTC(g('year'), g('month') - 1, g('day'), hr, g('minute'), g('second'));
        const offsetMs = tzDisplayMs - refUtcMs;
        return new Date(refUtcMs - offsetMs).toISOString();
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();

        if (!campaignName || !selectedWorkflowId || !sourceId) {
            toast.error('Please fill in all fields');
            return;
        }

        if ((callingWindowStart && !callingWindowEnd) || (!callingWindowStart && callingWindowEnd)) {
            toast.error('Both calling window start and end must be set');
            return;
        }

        setIsSubmitting(true);

        try {
            const accessToken = await getAccessToken();
            const response = await createCampaignApiV1CampaignCreatePost({
                body: {
                    name: campaignName,
                    workflow_id: parseInt(selectedWorkflowId),
                    source_type: sourceType,
                    source_id: sourceId,
                    scheduled_start_at: buildScheduledIso(),
                    calling_window_start: callingWindowStart || undefined,
                    calling_window_end: callingWindowEnd || undefined,
                    calling_window_timezone: callingWindowTimezone || undefined,
                },
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                }
            });

            if (response.data) {
                toast.success('Campaign created and started');
                router.push('/campaigns');
            } else if (response.error) {
                const errorDetail = response.error as { detail?: { error?: string; message?: string; reason?: string } | string };
                if (typeof errorDetail?.detail === 'object' && errorDetail.detail?.error === 'subscription_limit') {
                    toast.error(errorDetail.detail.message || 'Subscription limit reached');
                    router.push('/usage');
                    return;
                }
                const msg = typeof errorDetail?.detail === 'string'
                    ? errorDetail.detail
                    : (errorDetail?.detail as { message?: string })?.message || 'Failed to create campaign';
                toast.error(msg);
            }
        } catch (error) {
            console.error('Failed to create campaign:', error);
            toast.error('Failed to create campaign');
        } finally {
            setIsSubmitting(false);
        }
    };

    const handleBack = () => {
        router.push('/campaigns');
    };

    const handleSheetSelected = (sheetUrl: string) => {
        setSourceId(sheetUrl);
    };

    const handleFileUploaded = (fileKey: string, fileName: string) => {
        setSourceId(fileKey);
        setSelectedFileName(fileName);
    };

    return (
        <div className="container mx-auto p-6 space-y-6 max-w-2xl">
            <div>
                <Button
                    variant="ghost"
                    onClick={handleBack}
                    className="mb-4"
                >
                    <ArrowLeft className="h-4 w-4 mr-2" />
                    Back to Campaigns
                </Button>
                <h1 className="text-3xl font-bold mb-2">Create New Campaign</h1>
                <p className="text-muted-foreground">Set up a new campaign to execute workflows at scale</p>
            </div>

            <Card>
                <CardHeader>
                    <CardTitle>Campaign Details</CardTitle>
                    <CardDescription>
                        Configure your campaign settings
                    </CardDescription>
                </CardHeader>
                <CardContent>
                    <form onSubmit={handleSubmit} className="space-y-6">
                        <div className="space-y-2">
                            <Label htmlFor="campaign-name">Campaign Name</Label>
                            <Input
                                id="campaign-name"
                                placeholder="Enter campaign name"
                                value={campaignName}
                                onChange={(e) => setCampaignName(e.target.value)}
                                maxLength={255}
                                required
                            />
                            <p className="text-sm text-muted-foreground">
                                Choose a descriptive name for your campaign
                            </p>
                        </div>

                        <div className="space-y-2">
                            <Label htmlFor="workflow">Workflow</Label>
                            <Select
                                value={selectedWorkflowId}
                                onValueChange={setSelectedWorkflowId}
                                required
                            >
                                <SelectTrigger id="workflow">
                                    <SelectValue placeholder="Select a workflow" />
                                </SelectTrigger>
                                <SelectContent>
                                    {isLoadingWorkflows ? (
                                        <SelectItem value="loading" disabled>
                                            Loading workflows...
                                        </SelectItem>
                                    ) : workflows.length === 0 ? (
                                        <SelectItem value="none" disabled>
                                            No outbound workflows found
                                        </SelectItem>
                                    ) : (
                                        workflows.map((workflow) => (
                                            <SelectItem
                                                key={workflow.id}
                                                value={workflow.id.toString()}
                                            >
                                                {workflow.name}
                                            </SelectItem>
                                        ))
                                    )}
                                </SelectContent>
                            </Select>
                            <p className="text-sm text-muted-foreground">
                                Select an outbound workflow to execute for each contact
                            </p>
                        </div>

                        <div className="space-y-2">
                            <Label htmlFor="source-type">Data Source Type</Label>
                            <Select
                                value={sourceType}
                                onValueChange={(value) => {
                                    setSourceType(value as 'google-sheet' | 'csv');
                                    setSourceId('');
                                    setSelectedFileName('');
                                }}
                                required
                            >
                                <SelectTrigger id="source-type">
                                    <SelectValue placeholder="Select source type" />
                                </SelectTrigger>
                                <SelectContent>
                                    {/* <SelectItem value="google-sheet">Google Sheet</SelectItem> */}
                                    <SelectItem value="csv">CSV / Excel File</SelectItem>
                                </SelectContent>
                            </Select>
                            <p className="text-sm text-muted-foreground">
                                Choose where your contact data is stored
                            </p>
                        </div>

                        {sourceType === 'google-sheet' ? (
                            <GoogleSheetSelector
                                accessToken={userAccessToken}
                                onSheetSelected={handleSheetSelected}
                                selectedSheetUrl={sourceId}
                            />
                        ) : (
                            <CsvUploadSelector
                                accessToken={userAccessToken}
                                onFileUploaded={handleFileUploaded}
                                selectedFileName={selectedFileName}
                            />
                        )}

                        {/* Scheduling Section */}
                        <div className="border rounded-lg p-4 space-y-4 bg-muted/30">
                            <div className="space-y-3">
                                <div className="flex items-center gap-2 mb-1">
                                    <CalendarIcon className="h-4 w-4 text-muted-foreground" />
                                    <Label className="text-base font-semibold">Scheduled Start (Optional)</Label>
                                </div>
                                <p className="text-sm text-muted-foreground -mt-2">
                                    Leave empty to start immediately. Set a date to auto-start at the scheduled time.
                                </p>

                                <div className="flex flex-wrap items-end gap-3">
                                    <div className="space-y-1.5">
                                        <Label className="text-xs">Date</Label>
                                        <Popover open={calendarOpen} onOpenChange={setCalendarOpen}>
                                            <PopoverTrigger asChild>
                                                <Button
                                                    type="button"
                                                    variant="outline"
                                                    className={cn(
                                                        "w-[200px] justify-start text-left font-normal h-9",
                                                        !scheduledDate && "text-muted-foreground"
                                                    )}
                                                >
                                                    <CalendarIcon className="mr-2 h-4 w-4" />
                                                    {scheduledDate ? format(scheduledDate, 'MMM d, yyyy') : 'Pick a date'}
                                                </Button>
                                            </PopoverTrigger>
                                            <PopoverContent className="w-auto p-0" align="start">
                                                <Calendar
                                                    mode="single"
                                                    selected={scheduledDate}
                                                    onSelect={(day) => {
                                                        setScheduledDate(day);
                                                        setCalendarOpen(false);
                                                    }}
                                                    disabled={(date) => date < new Date(new Date().setHours(0, 0, 0, 0))}
                                                />
                                            </PopoverContent>
                                        </Popover>
                                    </div>

                                    {scheduledDate && (
                                        <TimePicker
                                            value={scheduledTime}
                                            onChange={setScheduledTime}
                                            label="Time"
                                        />
                                    )}

                                    {scheduledDate && (
                                        <Button
                                            type="button"
                                            variant="ghost"
                                            size="sm"
                                            className="text-xs text-muted-foreground h-9"
                                            onClick={() => {
                                                setScheduledDate(undefined);
                                                setScheduledTime('09:00');
                                            }}
                                        >
                                            Clear
                                        </Button>
                                    )}
                                </div>

                                {scheduledDate && (
                                    <p className="text-xs text-muted-foreground">
                                        Campaign will auto-start on{' '}
                                        <span className="text-foreground font-medium">
                                            {format(scheduledDate, 'EEEE, MMM d, yyyy')}
                                        </span>
                                        {' '}at{' '}
                                        <span className="text-foreground font-medium">
                                            {(() => {
                                                const { hour, minute, period } = parseTimeToComponents(scheduledTime);
                                                return `${hour}:${pad(parseInt(minute))} ${period}`;
                                            })()}
                                        </span>
                                        {' '}({callingWindowTimezone.replace(/_/g, ' ')})
                                    </p>
                                )}
                            </div>
                        </div>

                        {/* Daily Calling Window */}
                        <div className="border rounded-lg p-4 space-y-3 bg-muted/30">
                            <div className="flex items-center gap-2 mb-1">
                                <Clock className="h-4 w-4 text-muted-foreground" />
                                <Label className="text-base font-semibold">Daily Calling Window (Optional)</Label>
                            </div>
                            <p className="text-xs text-muted-foreground -mt-1">
                                Calls will only be made within this time window each day. Leave empty for 24/7 calling.
                            </p>

                            <div className="flex items-end gap-3 flex-wrap">
                                <TimePicker
                                    value={callingWindowStart || '09:00'}
                                    onChange={setCallingWindowStart}
                                    label="Start Time"
                                />
                                <span className="text-muted-foreground pb-2">to</span>
                                <TimePicker
                                    value={callingWindowEnd || '17:00'}
                                    onChange={setCallingWindowEnd}
                                    label="End Time"
                                />
                                {(callingWindowStart || callingWindowEnd) && (
                                    <Button
                                        type="button"
                                        variant="ghost"
                                        size="sm"
                                        className="text-xs text-muted-foreground h-9"
                                        onClick={() => {
                                            setCallingWindowStart('');
                                            setCallingWindowEnd('');
                                        }}
                                    >
                                        Clear
                                    </Button>
                                )}
                            </div>

                            <div className="space-y-1">
                                <Label htmlFor="timezone" className="text-xs">Timezone</Label>
                                <Select
                                    value={callingWindowTimezone}
                                    onValueChange={setCallingWindowTimezone}
                                >
                                    <SelectTrigger id="timezone" className="w-64">
                                        <SelectValue placeholder="Select timezone" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {COMMON_TIMEZONES.map((tz) => (
                                            <SelectItem key={tz} value={tz}>
                                                {tz.replace(/_/g, ' ')}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        </div>

                        <div className="flex gap-4 pt-4">
                            <Button
                                type="submit"
                                disabled={isSubmitting || !campaignName || !selectedWorkflowId || !sourceId}
                            >
                                {isSubmitting ? 'Creating & Starting...' : 'Create & Start Campaign'}
                            </Button>
                            <Button
                                type="button"
                                variant="outline"
                                onClick={handleBack}
                                disabled={isSubmitting}
                            >
                                Cancel
                            </Button>
                        </div>
                    </form>
                </CardContent>
            </Card>
        </div>
    );
}
