"use client";

import { format } from 'date-fns';
import {
    ArrowLeft,
    BarChart3,
    CalendarIcon,
    Clock,
    Phone,
    PhoneCall,
    PhoneForwarded,
    PhoneMissed,
    PhoneOff,
    RefreshCw,
    Timer,
    TrendingUp,
    Users,
} from 'lucide-react';

import { Spinner } from '@/components/ui/ai-loader';
import { useParams, useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';

import {
    getCampaignApiV1CampaignCampaignIdGet,
    getCampaignContactsApiV1CampaignCampaignIdContactsGet,
    getWorkflowApiV1WorkflowFetchWorkflowIdGet,
    updateCampaignScheduleApiV1CampaignCampaignIdSchedulePatch,
} from '@/client/sdk.gen';
import type {
    CampaignContactResponse,
    CampaignResponse,
} from '@/client/types.gen';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Progress } from '@/components/ui/progress';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';
import { getBackendUrl } from '@/lib/apiClient';
import { useAuth } from '@/lib/auth';

const HOURS_12 = Array.from({ length: 12 }, (_, i) => i + 1);
const MINUTES_5 = Array.from({ length: 12 }, (_, i) => i * 5);

function pad2(n: number): string {
    return n.toString().padStart(2, '0');
}

function parseTimeTo12h(time: string): { hour: string; minute: string; period: 'AM' | 'PM' } {
    if (!time) return { hour: '9', minute: '0', period: 'AM' };
    const [h, m] = time.split(':').map(Number);
    const period: 'AM' | 'PM' = h >= 12 ? 'PM' : 'AM';
    const hour = h === 0 ? '12' : h > 12 ? String(h - 12) : String(h);
    return { hour, minute: String(m), period };
}

function to24h(hour: string, minute: string, period: 'AM' | 'PM'): string {
    let h = parseInt(hour);
    if (period === 'AM' && h === 12) h = 0;
    if (period === 'PM' && h !== 12) h += 12;
    return `${pad2(h)}:${pad2(parseInt(minute))}`;
}

function DetailTimePicker({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
    const { hour, minute, period } = parseTimeTo12h(value);
    const update = (h?: string, m?: string, p?: 'AM' | 'PM') => {
        onChange(to24h(h ?? hour, m ?? minute, p ?? period));
    };
    return (
        <div className="space-y-1.5">
            <Label className="text-xs">{label}</Label>
            <div className="flex items-center gap-1.5">
                <Select value={hour} onValueChange={(h) => update(h)}>
                    <SelectTrigger className="w-[68px] h-9"><SelectValue /></SelectTrigger>
                    <SelectContent>{HOURS_12.map((h) => <SelectItem key={h} value={String(h)}>{h}</SelectItem>)}</SelectContent>
                </Select>
                <span className="text-muted-foreground font-medium">:</span>
                <Select value={String(parseInt(minute))} onValueChange={(m) => update(undefined, m)}>
                    <SelectTrigger className="w-[68px] h-9"><SelectValue /></SelectTrigger>
                    <SelectContent>{MINUTES_5.map((m) => <SelectItem key={m} value={String(m)}>{pad2(m)}</SelectItem>)}</SelectContent>
                </Select>
                <Select value={period} onValueChange={(p) => update(undefined, undefined, p as 'AM' | 'PM')}>
                    <SelectTrigger className="w-[68px] h-9"><SelectValue /></SelectTrigger>
                    <SelectContent><SelectItem value="AM">AM</SelectItem><SelectItem value="PM">PM</SelectItem></SelectContent>
                </Select>
            </div>
        </div>
    );
}

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

interface CampaignAnalytics {
    total_contacts: number;
    processed: number;
    failed: number;
    remaining: number;
    connected_calls: number;
    total_calls_made: number;
    avg_call_duration: number;
    total_call_duration: number;
    disposition_breakdown: Record<string, number>;
}

function formatDuration(seconds: number): string {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

const DISPOSITION_CONFIG: Record<string, { label: string; color: string; icon: typeof Phone }> = {
    completed: { label: 'Completed', color: 'text-emerald-400', icon: PhoneCall },
    'in-progress': { label: 'In Progress', color: 'text-primary', icon: PhoneForwarded },
    ringing: { label: 'Ringing', color: 'text-yellow-400', icon: Phone },
    busy: { label: 'Busy', color: 'text-orange-400', icon: PhoneOff },
    'no-answer': { label: 'No Answer', color: 'text-red-400', icon: PhoneMissed },
    failed: { label: 'Failed', color: 'text-red-500', icon: PhoneOff },
    canceled: { label: 'Canceled', color: 'text-zinc-400', icon: PhoneOff },
    unknown: { label: 'Unknown', color: 'text-zinc-500', icon: Phone },
};

export default function CampaignDetailPage() {
    const { user, getAccessToken, redirectToLogin, loading } = useAuth();
    const router = useRouter();
    const params = useParams();
    const campaignId = parseInt(params.campaignId as string);

    useEffect(() => {
        if (!loading && !user) redirectToLogin();
    }, [loading, user, redirectToLogin]);

    const [campaign, setCampaign] = useState<CampaignResponse | null>(null);
    const [isLoadingCampaign, setIsLoadingCampaign] = useState(true);

    const [analytics, setAnalytics] = useState<CampaignAnalytics | null>(null);
    const [isLoadingAnalytics, setIsLoadingAnalytics] = useState(false);

    const [contacts, setContacts] = useState<CampaignContactResponse[]>([]);
    const [contactsTotal, setContactsTotal] = useState(0);
    const [contactsOffset, setContactsOffset] = useState(0);
    const [contactsLimit] = useState(50);
    const [contactsStatusFilter, setContactsStatusFilter] = useState<string>('all');
    const [isLoadingContacts, setIsLoadingContacts] = useState(false);

    const [editScheduledDate, setEditScheduledDate] = useState<Date | undefined>(undefined);
    const [editScheduledTime, setEditScheduledTime] = useState('09:00');
    const [editCalendarOpen, setEditCalendarOpen] = useState(false);
    const [editWindowStart, setEditWindowStart] = useState('');
    const [editWindowEnd, setEditWindowEnd] = useState('');
    const [editWindowTz, setEditWindowTz] = useState('UTC');
    const [isSavingSchedule, setIsSavingSchedule] = useState(false);

    const fetchCampaign = useCallback(async (showLoading = false) => {
        if (!user) return;
        if (showLoading) setIsLoadingCampaign(true);
        try {
            const accessToken = await getAccessToken();
            const response = await getCampaignApiV1CampaignCampaignIdGet({
                path: { campaign_id: campaignId },
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            if (response.data) setCampaign(response.data);
        } catch (error) {
            console.error('Failed to fetch campaign:', error);
            if (showLoading) toast.error('Failed to load campaign details');
        } finally {
            if (showLoading) setIsLoadingCampaign(false);
        }
    }, [user, getAccessToken, campaignId]);

    const fetchAnalytics = useCallback(async () => {
        if (!user) return;
        setIsLoadingAnalytics(true);
        try {
            const accessToken = await getAccessToken();
            const baseUrl = getBackendUrl();
            const res = await fetch(`${baseUrl}/api/v1/campaign/${campaignId}/analytics`, {
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            if (res.ok) {
                const data = await res.json();
                setAnalytics(data);
            }
        } catch (error) {
            console.error('Failed to fetch analytics:', error);
        } finally {
            setIsLoadingAnalytics(false);
        }
    }, [user, getAccessToken, campaignId]);

    const fetchContacts = useCallback(async (offset = 0) => {
        if (!user) return;
        setIsLoadingContacts(true);
        try {
            const accessToken = await getAccessToken();
            const response = await getCampaignContactsApiV1CampaignCampaignIdContactsGet({
                path: { campaign_id: campaignId },
                query: {
                    status: contactsStatusFilter === 'all' ? undefined : contactsStatusFilter,
                    offset,
                    limit: contactsLimit,
                },
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            if (response.data) {
                setContacts(response.data.contacts);
                setContactsTotal(response.data.total);
                setContactsOffset(offset);
            }
        } catch (error) {
            console.error('Failed to fetch contacts:', error);
        } finally {
            setIsLoadingContacts(false);
        }
    }, [user, getAccessToken, campaignId, contactsStatusFilter, contactsLimit]);

    useEffect(() => {
        fetchCampaign(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [user, campaignId]);

    const autoRefreshRef = useRef<ReturnType<typeof setInterval> | null>(null);
    useEffect(() => {
        if (autoRefreshRef.current) clearInterval(autoRefreshRef.current);
        if (campaign?.state === 'running' || campaign?.state === 'syncing') {
            autoRefreshRef.current = setInterval(() => {
                fetchCampaign();
                if (analytics) fetchAnalytics();
            }, 5000);
        }
        return () => {
            if (autoRefreshRef.current) clearInterval(autoRefreshRef.current);
        };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [campaign?.state]);

    const scheduleFieldsInitRef = useRef(false);
    useEffect(() => {
        if (campaign && !scheduleFieldsInitRef.current) {
            scheduleFieldsInitRef.current = true;
            if (campaign.scheduled_start_at) {
                const d = new Date(campaign.scheduled_start_at);
                setEditScheduledDate(d);
                setEditScheduledTime(`${pad2(d.getHours())}:${pad2(d.getMinutes())}`);
            } else {
                setEditScheduledDate(undefined);
                setEditScheduledTime('09:00');
            }
            setEditWindowStart(campaign.calling_window_start || '');
            setEditWindowEnd(campaign.calling_window_end || '');
            setEditWindowTz(campaign.calling_window_timezone || 'UTC');
        }
    }, [campaign]);

    const handleBack = () => router.push('/campaigns');
    // Resolve the workflow's opaque public_id token before navigating so the
    // enumerable integer id never appears in the URL.
    const gotoWorkflow = async (suffix = '') => {
        if (!campaign) return;
        try {
            const accessToken = await getAccessToken();
            const res = await getWorkflowApiV1WorkflowFetchWorkflowIdGet({
                path: { workflow_id: campaign.workflow_id },
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            const token = res.data?.public_id ?? campaign.workflow_id;
            router.push(`/workflow/${token}${suffix}`);
        } catch {
            router.push(`/workflow/${campaign.workflow_id}${suffix}`);
        }
    };
    const handleWorkflowClick = () => { void gotoWorkflow(); };
    const handleRunClick = (runId: number) => { void gotoWorkflow(`/run/${runId}`); };

    const handleDownloadCsv = async () => {
        if (!user || !campaign || campaign.source_type !== 'csv') return;
        try {
            const accessToken = await getAccessToken();
            const { getCampaignSourceDownloadUrlApiV1CampaignCampaignIdSourceDownloadUrlGet } = await import('@/client/sdk.gen');
            const response = await getCampaignSourceDownloadUrlApiV1CampaignCampaignIdSourceDownloadUrlGet({
                path: { campaign_id: campaignId },
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            if (response.data?.download_url) {
                window.open(response.data.download_url, '_blank');
            } else {
                toast.error('Failed to get download URL');
            }
        } catch {
            toast.error('Failed to download CSV file');
        }
    };

    const handleSaveSchedule = async () => {
        if (!user || !campaign) return;
        if ((editWindowStart && !editWindowEnd) || (!editWindowStart && editWindowEnd)) {
            toast.error('Both start and end times must be set for the calling window');
            return;
        }
        let scheduledIso: string | null = null;
        if (editScheduledDate) {
            const [h, m] = editScheduledTime.split(':').map(Number);
            const dt = new Date(editScheduledDate);
            dt.setHours(h, m, 0, 0);
            scheduledIso = dt.toISOString();
        }
        setIsSavingSchedule(true);
        try {
            const accessToken = await getAccessToken();
            const response = await updateCampaignScheduleApiV1CampaignCampaignIdSchedulePatch({
                path: { campaign_id: campaignId },
                body: {
                    scheduled_start_at: scheduledIso,
                    calling_window_start: editWindowStart || null,
                    calling_window_end: editWindowEnd || null,
                    calling_window_timezone: editWindowTz || null,
                },
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            if (response.data) {
                setCampaign(response.data);
                toast.success('Schedule updated');
            } else {
                toast.error('Failed to update schedule');
            }
        } catch {
            toast.error('Failed to update schedule');
        } finally {
            setIsSavingSchedule(false);
        }
    };

    const formatDate = (ds: string) => new Date(ds).toLocaleDateString();
    const formatDateTime = (ds: string) => new Date(ds).toLocaleString();

    const getStateBadgeVariant = (state: string) => {
        switch (state) {
            case 'created': return 'secondary';
            case 'scheduled': return 'outline';
            case 'running': case 'syncing': return 'default';
            case 'paused': return 'outline';
            case 'completed': return 'secondary';
            case 'failed': return 'destructive';
            default: return 'secondary';
        }
    };

    const getContactStatusBadge = (status: string) => {
        switch (status) {
            case 'queued': return 'secondary';
            case 'processed': return 'default';
            case 'failed': return 'destructive';
            default: return 'secondary';
        }
    };

    const progressPercent = useMemo(() => {
        if (!campaign || !campaign.total_rows) return 0;
        return Math.round((campaign.processed_rows / campaign.total_rows) * 100);
    }, [campaign]);

    if (isLoadingCampaign) {
        return (
            <div className="container mx-auto p-6 space-y-6">
                <div className="animate-pulse space-y-4">
                    <div className="h-8 bg-muted rounded w-1/4" />
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                        {[...Array(4)].map((_, i) => (
                            <div key={i} className="h-24 bg-muted rounded-xl" />
                        ))}
                    </div>
                    <div className="h-96 bg-muted rounded-xl" />
                </div>
            </div>
        );
    }

    if (!campaign) {
        return (
            <div className="container mx-auto p-6">
                <p className="text-center text-muted-foreground py-20">Campaign not found</p>
            </div>
        );
    }

    return (
        <div className="container mx-auto p-4 sm:p-6 max-w-6xl space-y-6">
            {/* Header */}
            <div>
                <Button variant="ghost" onClick={handleBack} className="mb-3 -ml-2 text-muted-foreground hover:text-foreground">
                    <ArrowLeft className="h-4 w-4 mr-1.5" />
                    Campaigns
                </Button>
                <div className="flex flex-col sm:flex-row justify-between items-start gap-4">
                    <div className="space-y-2">
                        <div className="flex items-center gap-3">
                            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">{campaign.name}</h1>
                            <Badge
                                variant={getStateBadgeVariant(campaign.state)}
                                className="capitalize"
                            >
                                {campaign.state}
                            </Badge>
                        </div>
                        <div className="flex items-center gap-4 text-sm text-muted-foreground">
                            <span>Created {formatDate(campaign.created_at)}</span>
                            <span className="text-border">|</span>
                            <button
                                onClick={handleWorkflowClick}
                                className="text-primary hover:underline"
                            >
                                {campaign.workflow_name}
                            </button>
                            {campaign.scheduled_start_at && campaign.state === 'scheduled' && (
                                <>
                                    <span className="text-border">|</span>
                                    <span className="flex items-center gap-1">
                                        <CalendarIcon className="h-3 w-3" />
                                        Starts {formatDateTime(campaign.scheduled_start_at)}
                                    </span>
                                </>
                            )}
                        </div>
                    </div>
                </div>
            </div>

            {/* Quick Stats Cards */}
            {(campaign.total_rows ?? 0) > 0 && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <Card className="border-border/50 bg-card/50">
                        <CardContent className="p-4">
                            <div className="flex items-center gap-3">
                                <div className="p-2 rounded-lg bg-primary/10">
                                    <Users className="h-4 w-4 text-primary" />
                                </div>
                                <div>
                                    <p className="text-2xl font-bold">{campaign.total_rows ?? 0}</p>
                                    <p className="text-xs text-muted-foreground">Total Contacts</p>
                                </div>
                            </div>
                        </CardContent>
                    </Card>
                    <Card className="border-border/50 bg-card/50">
                        <CardContent className="p-4">
                            <div className="flex items-center gap-3">
                                <div className="p-2 rounded-lg bg-emerald-500/10">
                                    <PhoneCall className="h-4 w-4 text-emerald-400" />
                                </div>
                                <div>
                                    <p className="text-2xl font-bold text-emerald-400">{campaign.completed_calls}</p>
                                    <p className="text-xs text-muted-foreground">Connected</p>
                                </div>
                            </div>
                        </CardContent>
                    </Card>
                    <Card className="border-border/50 bg-card/50">
                        <CardContent className="p-4">
                            <div className="flex items-center gap-3">
                                <div className="p-2 rounded-lg bg-primary/10">
                                    <TrendingUp className="h-4 w-4 text-primary" />
                                </div>
                                <div>
                                    <p className="text-2xl font-bold text-primary">{progressPercent}%</p>
                                    <p className="text-xs text-muted-foreground">Progress</p>
                                </div>
                            </div>
                        </CardContent>
                    </Card>
                    <Card className="border-border/50 bg-card/50">
                        <CardContent className="p-4">
                            <div className="flex items-center gap-3">
                                <div className="p-2 rounded-lg bg-red-500/10">
                                    <PhoneOff className="h-4 w-4 text-red-400" />
                                </div>
                                <div>
                                    <p className="text-2xl font-bold text-red-400">{campaign.failed_rows}</p>
                                    <p className="text-xs text-muted-foreground">Failed</p>
                                </div>
                            </div>
                        </CardContent>
                    </Card>
                </div>
            )}

            {/* Progress Bar */}
            {(campaign.total_rows ?? 0) > 0 && (
                <div className="space-y-1.5">
                    <div className="flex justify-between text-xs text-muted-foreground">
                        <span>{campaign.processed_rows} of {campaign.total_rows} processed</span>
                        <span>{progressPercent}%</span>
                    </div>
                    <Progress value={progressPercent} className="h-2" />
                </div>
            )}

            {/* Tabs */}
            <Tabs defaultValue="overview" className="space-y-4">
                <TabsList className="bg-muted/50">
                    <TabsTrigger value="overview">Overview</TabsTrigger>
                    <TabsTrigger value="contacts" onClick={() => { if (contacts.length === 0) fetchContacts(0); }}>
                        Contacts
                    </TabsTrigger>
                    <TabsTrigger value="analytics" onClick={() => { if (!analytics) fetchAnalytics(); }}>
                        Analytics
                    </TabsTrigger>
                    <TabsTrigger value="schedule">Schedule</TabsTrigger>
                </TabsList>

                {/* === OVERVIEW TAB === */}
                <TabsContent value="overview" className="space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {/* Campaign Info */}
                        <Card className="border-border/50">
                            <CardHeader className="pb-3">
                                <CardTitle className="text-base font-semibold">Campaign Info</CardTitle>
                            </CardHeader>
                            <CardContent className="space-y-4">
                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <p className="text-xs text-muted-foreground mb-1">Workflow</p>
                                        <button
                                            onClick={handleWorkflowClick}
                                            className="text-sm text-primary hover:underline font-medium"
                                        >
                                            {campaign.workflow_name}
                                        </button>
                                    </div>
                                    <div>
                                        <p className="text-xs text-muted-foreground mb-1">Source Type</p>
                                        <p className="text-sm font-medium capitalize">{campaign.source_type.replace('-', ' ')}</p>
                                    </div>
                                    <div>
                                        <p className="text-xs text-muted-foreground mb-1">State</p>
                                        <Badge variant={getStateBadgeVariant(campaign.state)} className="capitalize">
                                            {campaign.state}
                                        </Badge>
                                    </div>
                                    <div>
                                        <p className="text-xs text-muted-foreground mb-1">Source</p>
                                        {campaign.source_type === 'csv' ? (
                                            <button
                                                onClick={handleDownloadCsv}
                                                className="text-sm text-primary hover:underline break-all"
                                            >
                                                {campaign.source_id.split('/').pop()}
                                            </button>
                                        ) : (
                                            <a
                                                href={campaign.source_id}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="text-sm text-primary hover:underline break-all"
                                            >
                                                View Sheet
                                            </a>
                                        )}
                                    </div>
                                </div>
                            </CardContent>
                        </Card>

                        {/* Timeline */}
                        <Card className="border-border/50">
                            <CardHeader className="pb-3">
                                <CardTitle className="text-base font-semibold">Timeline</CardTitle>
                            </CardHeader>
                            <CardContent>
                                <div className="space-y-3">
                                    <div className="flex items-center gap-3">
                                        <div className="h-2 w-2 rounded-full bg-muted-foreground" />
                                        <div className="flex-1">
                                            <p className="text-sm">Created</p>
                                            <p className="text-xs text-muted-foreground">{formatDateTime(campaign.created_at)}</p>
                                        </div>
                                    </div>
                                    {campaign.scheduled_start_at && (
                                        <div className="flex items-center gap-3">
                                            <div className="h-2 w-2 rounded-full bg-yellow-400" />
                                            <div className="flex-1">
                                                <p className="text-sm">Scheduled Start</p>
                                                <p className="text-xs text-muted-foreground">{formatDateTime(campaign.scheduled_start_at)}</p>
                                            </div>
                                        </div>
                                    )}
                                    {campaign.started_at && (
                                        <div className="flex items-center gap-3">
                                            <div className="h-2 w-2 rounded-full bg-emerald-400" />
                                            <div className="flex-1">
                                                <p className="text-sm">Started</p>
                                                <p className="text-xs text-muted-foreground">{formatDateTime(campaign.started_at)}</p>
                                            </div>
                                        </div>
                                    )}
                                    {campaign.completed_at && (
                                        <div className="flex items-center gap-3">
                                            <div className="h-2 w-2 rounded-full bg-primary" />
                                            <div className="flex-1">
                                                <p className="text-sm">Completed</p>
                                                <p className="text-xs text-muted-foreground">{formatDateTime(campaign.completed_at)}</p>
                                            </div>
                                        </div>
                                    )}
                                    {campaign.calling_window_start && (
                                        <div className="flex items-center gap-3">
                                            <div className="h-2 w-2 rounded-full bg-primary" />
                                            <div className="flex-1">
                                                <p className="text-sm">Calling Window</p>
                                                <p className="text-xs text-muted-foreground">
                                                    {campaign.calling_window_start} - {campaign.calling_window_end}{' '}
                                                    ({campaign.calling_window_timezone})
                                                </p>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </CardContent>
                        </Card>
                    </div>
                </TabsContent>

                {/* === CONTACTS TAB === */}
                <TabsContent value="contacts" className="space-y-4">
                    <Card className="border-border/50">
                        <CardHeader className="pb-3">
                            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
                                <div>
                                    <CardTitle className="text-base font-semibold flex items-center gap-2">
                                        <Users className="h-4 w-4" />
                                        Contacts
                                    </CardTitle>
                                    <CardDescription className="text-xs mt-1">
                                        {contactsTotal} total contacts{' '}
                                        {contactsStatusFilter !== 'all' && `(filtered: ${contactsStatusFilter})`}
                                    </CardDescription>
                                </div>
                                <div className="flex items-center gap-2">
                                    <Select
                                        value={contactsStatusFilter}
                                        onValueChange={(v) => {
                                            setContactsStatusFilter(v);
                                            setContactsOffset(0);
                                        }}
                                    >
                                        <SelectTrigger className="w-32 h-8 text-xs">
                                            <SelectValue placeholder="Filter" />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="all">All</SelectItem>
                                            <SelectItem value="queued">Queued</SelectItem>
                                            <SelectItem value="processed">Processed</SelectItem>
                                            <SelectItem value="failed">Failed</SelectItem>
                                        </SelectContent>
                                    </Select>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        className="h-8 w-8 p-0"
                                        onClick={() => fetchContacts(contactsOffset)}
                                    >
                                        <RefreshCw className="h-3.5 w-3.5" />
                                    </Button>
                                </div>
                            </div>
                        </CardHeader>
                        <CardContent>
                            {isLoadingContacts ? (
                                <div className="flex items-center justify-center py-16">
                                    <Spinner size="md" />
                                </div>
                            ) : contacts.length > 0 ? (
                                <>
                                    <div className="overflow-x-auto rounded-lg border border-border/50">
                                        <Table>
                                            <TableHeader>
                                                <TableRow className="bg-muted/30">
                                                    <TableHead className="text-xs font-medium">Contact</TableHead>
                                                    <TableHead className="text-xs font-medium">Phone</TableHead>
                                                    <TableHead className="text-xs font-medium">Status</TableHead>
                                                    <TableHead className="text-xs font-medium">Disposition</TableHead>
                                                    <TableHead className="text-xs font-medium">Duration</TableHead>
                                                    <TableHead className="text-xs font-medium">Processed At</TableHead>
                                                </TableRow>
                                            </TableHeader>
                                            <TableBody>
                                                {contacts.map((contact) => (
                                                    <TableRow
                                                        key={contact.id}
                                                        className={cn(
                                                            "transition-colors",
                                                            contact.workflow_run_id && 'cursor-pointer hover:bg-muted/50'
                                                        )}
                                                        onClick={() => {
                                                            if (contact.workflow_run_id) handleRunClick(contact.workflow_run_id);
                                                        }}
                                                    >
                                                        <TableCell>
                                                            <p className="text-sm font-medium">
                                                                {contact.first_name} {contact.last_name}
                                                            </p>
                                                        </TableCell>
                                                        <TableCell className="font-mono text-xs text-muted-foreground">
                                                            {contact.phone_number}
                                                        </TableCell>
                                                        <TableCell>
                                                            <Badge
                                                                variant={getContactStatusBadge(contact.status)}
                                                                className="text-[10px] font-medium"
                                                            >
                                                                {contact.status}
                                                            </Badge>
                                                        </TableCell>
                                                        <TableCell>
                                                            {contact.disposition ? (
                                                                <span className={cn(
                                                                    "text-xs capitalize font-medium",
                                                                    DISPOSITION_CONFIG[contact.disposition]?.color || 'text-muted-foreground'
                                                                )}>
                                                                    {DISPOSITION_CONFIG[contact.disposition]?.label || contact.disposition}
                                                                </span>
                                                            ) : (
                                                                <span className="text-xs text-muted-foreground">-</span>
                                                            )}
                                                        </TableCell>
                                                        <TableCell>
                                                            {contact.call_duration != null && contact.call_duration > 0 ? (
                                                                <span className="text-xs">{formatDuration(contact.call_duration)}</span>
                                                            ) : (
                                                                <span className="text-xs text-muted-foreground">-</span>
                                                            )}
                                                        </TableCell>
                                                        <TableCell className="text-xs text-muted-foreground">
                                                            {contact.processed_at
                                                                ? new Date(contact.processed_at).toLocaleString()
                                                                : '-'}
                                                        </TableCell>
                                                    </TableRow>
                                                ))}
                                            </TableBody>
                                        </Table>
                                    </div>
                                    {contactsTotal > contactsLimit && (
                                        <div className="flex items-center justify-between pt-4">
                                            <span className="text-xs text-muted-foreground">
                                                {contactsOffset + 1}-{Math.min(contactsOffset + contactsLimit, contactsTotal)} of {contactsTotal}
                                            </span>
                                            <div className="flex gap-2">
                                                <Button
                                                    variant="outline"
                                                    size="sm"
                                                    className="h-7 text-xs"
                                                    disabled={contactsOffset === 0}
                                                    onClick={() => fetchContacts(Math.max(0, contactsOffset - contactsLimit))}
                                                >
                                                    Previous
                                                </Button>
                                                <Button
                                                    variant="outline"
                                                    size="sm"
                                                    className="h-7 text-xs"
                                                    disabled={contactsOffset + contactsLimit >= contactsTotal}
                                                    onClick={() => fetchContacts(contactsOffset + contactsLimit)}
                                                >
                                                    Next
                                                </Button>
                                            </div>
                                        </div>
                                    )}
                                </>
                            ) : (
                                <div className="text-center py-16 text-muted-foreground">
                                    <Users className="h-8 w-8 mx-auto mb-3 opacity-30" />
                                    <p className="text-sm">No contacts found</p>
                                    {campaign.state === 'created' && (
                                        <p className="text-xs mt-1 text-muted-foreground/70">
                                            Contacts will appear after the campaign starts.
                                        </p>
                                    )}
                                </div>
                            )}
                        </CardContent>
                    </Card>
                </TabsContent>

                {/* === ANALYTICS TAB === */}
                <TabsContent value="analytics" className="space-y-4">
                    {isLoadingAnalytics ? (
                        <div className="flex items-center justify-center py-20">
                            <Spinner size="md" />
                        </div>
                    ) : analytics ? (
                        <>
                            {/* Key Metrics */}
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                                <Card className="border-border/50 bg-gradient-to-br from-emerald-500/5 to-emerald-500/0">
                                    <CardContent className="p-4 flex flex-col items-center text-center">
                                        <PhoneCall className="h-5 w-5 text-emerald-400 mb-2" />
                                        <p className="text-2xl font-bold text-emerald-400">{analytics.connected_calls}</p>
                                        <p className="text-[11px] text-muted-foreground">Connected Calls</p>
                                    </CardContent>
                                </Card>
                                <Card className="border-border/50 bg-gradient-to-br from-primary/5 to-primary/0">
                                    <CardContent className="p-4 flex flex-col items-center text-center">
                                        <Phone className="h-5 w-5 text-primary mb-2" />
                                        <p className="text-2xl font-bold text-primary">{analytics.total_calls_made}</p>
                                        <p className="text-[11px] text-muted-foreground">Total Calls Made</p>
                                    </CardContent>
                                </Card>
                                <Card className="border-border/50 bg-gradient-to-br from-purple-500/5 to-purple-500/0">
                                    <CardContent className="p-4 flex flex-col items-center text-center">
                                        <Timer className="h-5 w-5 text-purple-400 mb-2" />
                                        <p className="text-2xl font-bold text-purple-400">{formatDuration(analytics.avg_call_duration)}</p>
                                        <p className="text-[11px] text-muted-foreground">Avg Duration</p>
                                    </CardContent>
                                </Card>
                                <Card className="border-border/50 bg-gradient-to-br from-amber-500/5 to-amber-500/0">
                                    <CardContent className="p-4 flex flex-col items-center text-center">
                                        <Clock className="h-5 w-5 text-amber-400 mb-2" />
                                        <p className="text-2xl font-bold text-amber-400">{formatDuration(analytics.total_call_duration)}</p>
                                        <p className="text-[11px] text-muted-foreground">Total Talk Time</p>
                                    </CardContent>
                                </Card>
                            </div>

                            {/* Connection Rate */}
                            {analytics.total_calls_made > 0 && (
                                <Card className="border-border/50">
                                    <CardHeader className="pb-3">
                                        <CardTitle className="text-base font-semibold flex items-center gap-2">
                                            <TrendingUp className="h-4 w-4" />
                                            Connection Rate
                                        </CardTitle>
                                    </CardHeader>
                                    <CardContent>
                                        <div className="flex items-center gap-4">
                                            <div className="flex-1">
                                                <div className="flex justify-between text-sm mb-2">
                                                    <span className="text-muted-foreground">
                                                        {analytics.connected_calls} of {analytics.total_calls_made} calls connected
                                                    </span>
                                                    <span className="font-bold text-emerald-400">
                                                        {Math.round((analytics.connected_calls / analytics.total_calls_made) * 100)}%
                                                    </span>
                                                </div>
                                                <Progress
                                                    value={(analytics.connected_calls / analytics.total_calls_made) * 100}
                                                    className="h-3"
                                                />
                                            </div>
                                        </div>
                                    </CardContent>
                                </Card>
                            )}

                            {/* Disposition Breakdown */}
                            {Object.keys(analytics.disposition_breakdown).length > 0 && (
                                <Card className="border-border/50">
                                    <CardHeader className="pb-3">
                                        <CardTitle className="text-base font-semibold flex items-center gap-2">
                                            <BarChart3 className="h-4 w-4" />
                                            Call Outcomes
                                        </CardTitle>
                                        <CardDescription className="text-xs">
                                            Breakdown of call dispositions
                                        </CardDescription>
                                    </CardHeader>
                                    <CardContent>
                                        <div className="space-y-3">
                                            {Object.entries(analytics.disposition_breakdown)
                                                .sort(([, a], [, b]) => b - a)
                                                .map(([disposition, count]) => {
                                                    const config = DISPOSITION_CONFIG[disposition] || DISPOSITION_CONFIG.unknown;
                                                    const Icon = config.icon;
                                                    const pct = analytics.total_calls_made > 0
                                                        ? Math.round((count / analytics.total_calls_made) * 100)
                                                        : 0;
                                                    return (
                                                        <div key={disposition} className="flex items-center gap-3">
                                                            <Icon className={cn("h-4 w-4 shrink-0", config.color)} />
                                                            <div className="flex-1 min-w-0">
                                                                <div className="flex justify-between items-center mb-1">
                                                                    <span className="text-sm font-medium capitalize">
                                                                        {config.label}
                                                                    </span>
                                                                    <span className="text-xs text-muted-foreground">
                                                                        {count} ({pct}%)
                                                                    </span>
                                                                </div>
                                                                <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                                                                    <div
                                                                        className={cn(
                                                                            "h-full rounded-full transition-all",
                                                                            disposition === 'completed' && 'bg-emerald-400',
                                                                            disposition === 'in-progress' && 'bg-primary',
                                                                            disposition === 'ringing' && 'bg-yellow-400',
                                                                            disposition === 'busy' && 'bg-orange-400',
                                                                            disposition === 'no-answer' && 'bg-red-400',
                                                                            disposition === 'failed' && 'bg-red-500',
                                                                            !['completed', 'in-progress', 'ringing', 'busy', 'no-answer', 'failed'].includes(disposition) && 'bg-zinc-400',
                                                                        )}
                                                                        style={{ width: `${pct}%` }}
                                                                    />
                                                                </div>
                                                            </div>
                                                        </div>
                                                    );
                                                })}
                                        </div>
                                    </CardContent>
                                </Card>
                            )}

                            {/* Campaign Progress Detail */}
                            <Card className="border-border/50">
                                <CardHeader className="pb-3">
                                    <CardTitle className="text-base font-semibold">Progress Detail</CardTitle>
                                </CardHeader>
                                <CardContent>
                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                                        <div className="text-center p-3 rounded-lg bg-muted/30">
                                            <p className="text-xl font-bold">{analytics.total_contacts}</p>
                                            <p className="text-xs text-muted-foreground">Total Contacts</p>
                                        </div>
                                        <div className="text-center p-3 rounded-lg bg-emerald-500/5">
                                            <p className="text-xl font-bold text-emerald-400">{analytics.processed}</p>
                                            <p className="text-xs text-muted-foreground">Processed</p>
                                        </div>
                                        <div className="text-center p-3 rounded-lg bg-red-500/5">
                                            <p className="text-xl font-bold text-red-400">{analytics.failed}</p>
                                            <p className="text-xs text-muted-foreground">Failed</p>
                                        </div>
                                        <div className="text-center p-3 rounded-lg bg-primary/5">
                                            <p className="text-xl font-bold text-primary">{analytics.remaining}</p>
                                            <p className="text-xs text-muted-foreground">Remaining</p>
                                        </div>
                                    </div>
                                </CardContent>
                            </Card>

                            {/* Refresh */}
                            <div className="flex justify-center">
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={fetchAnalytics}
                                    className="text-xs"
                                >
                                    <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
                                    Refresh Analytics
                                </Button>
                            </div>
                        </>
                    ) : (
                        <div className="text-center py-20 text-muted-foreground">
                            <BarChart3 className="h-8 w-8 mx-auto mb-3 opacity-30" />
                            <p className="text-sm">No analytics data available yet</p>
                            <p className="text-xs mt-1 text-muted-foreground/70">
                                Analytics will be available once calls are made.
                            </p>
                        </div>
                    )}
                </TabsContent>

                {/* === SCHEDULE TAB === */}
                <TabsContent value="schedule" className="space-y-4">
                    <Card className="border-border/50">
                        <CardHeader className="pb-3">
                            <CardTitle className="text-base font-semibold flex items-center gap-2">
                                <CalendarIcon className="h-4 w-4" />
                                Campaign Schedule
                            </CardTitle>
                            <CardDescription className="text-xs">
                                {campaign.state === 'created' || campaign.state === 'scheduled'
                                    ? 'Configure when this campaign should run'
                                    : 'Schedule settings (read-only for active campaigns)'}
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-6">
                            {/* Current schedule */}
                            {(campaign.scheduled_start_at || campaign.calling_window_start) && (
                                <div className="rounded-lg border border-border/50 bg-muted/20 p-4 space-y-3">
                                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Current Schedule</p>
                                    {campaign.scheduled_start_at && (
                                        <div className="flex items-center gap-2.5">
                                            <CalendarIcon className="h-3.5 w-3.5 text-muted-foreground" />
                                            <p className="text-sm">
                                                <span className="text-muted-foreground">Scheduled start:</span>{' '}
                                                <span className="font-medium">{formatDateTime(campaign.scheduled_start_at)}</span>
                                            </p>
                                        </div>
                                    )}
                                    {campaign.calling_window_start && (
                                        <div className="flex items-center gap-2.5">
                                            <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                                            <p className="text-sm">
                                                <span className="text-muted-foreground">Calling window:</span>{' '}
                                                <span className="font-medium">
                                                    {campaign.calling_window_start} - {campaign.calling_window_end}
                                                </span>{' '}
                                                <span className="text-xs text-muted-foreground">({campaign.calling_window_timezone})</span>
                                            </p>
                                        </div>
                                    )}
                                </div>
                            )}

                            {(campaign.state === 'created' || campaign.state === 'scheduled') ? (
                                <div className="space-y-5">
                                    <div className="space-y-3">
                                        <Label className="text-sm font-medium">Scheduled Start</Label>
                                        <div className="flex flex-wrap items-end gap-3">
                                            <div className="space-y-1.5">
                                                <Label className="text-xs">Date</Label>
                                                <Popover open={editCalendarOpen} onOpenChange={setEditCalendarOpen}>
                                                    <PopoverTrigger asChild>
                                                        <Button
                                                            variant="outline"
                                                            className={cn(
                                                                "w-[200px] justify-start text-left font-normal h-9",
                                                                !editScheduledDate && "text-muted-foreground"
                                                            )}
                                                        >
                                                            <CalendarIcon className="mr-2 h-4 w-4" />
                                                            {editScheduledDate ? format(editScheduledDate, 'MMM d, yyyy') : 'Pick a date'}
                                                        </Button>
                                                    </PopoverTrigger>
                                                    <PopoverContent className="w-auto p-0" align="start">
                                                        <Calendar
                                                            mode="single"
                                                            selected={editScheduledDate}
                                                            onSelect={(day) => {
                                                                setEditScheduledDate(day);
                                                                setEditCalendarOpen(false);
                                                            }}
                                                            disabled={(date) => date < new Date(new Date().setHours(0, 0, 0, 0))}
                                                        />
                                                    </PopoverContent>
                                                </Popover>
                                            </div>
                                            {editScheduledDate && (
                                                <DetailTimePicker value={editScheduledTime} onChange={setEditScheduledTime} label="Time" />
                                            )}
                                            {editScheduledDate && (
                                                <Button
                                                    type="button"
                                                    variant="ghost"
                                                    size="sm"
                                                    className="text-xs text-muted-foreground h-9"
                                                    onClick={() => { setEditScheduledDate(undefined); setEditScheduledTime('09:00'); }}
                                                >
                                                    Clear
                                                </Button>
                                            )}
                                        </div>
                                        {editScheduledDate && (
                                            <p className="text-xs text-muted-foreground">
                                                Campaign will auto-start on{' '}
                                                <span className="text-foreground font-medium">{format(editScheduledDate, 'EEEE, MMM d, yyyy')}</span>
                                                {' '}at{' '}
                                                <span className="text-foreground font-medium">
                                                    {(() => { const { hour, minute, period } = parseTimeTo12h(editScheduledTime); return `${hour}:${pad2(parseInt(minute))} ${period}`; })()}
                                                </span>
                                            </p>
                                        )}
                                        {!editScheduledDate && (
                                            <p className="text-xs text-muted-foreground">Leave empty to start manually</p>
                                        )}
                                    </div>

                                    <div className="border-t border-border/50 pt-4 space-y-3">
                                        <div className="flex items-center gap-2">
                                            <Clock className="h-4 w-4 text-muted-foreground" />
                                            <Label className="text-sm font-medium">Daily Calling Window</Label>
                                        </div>
                                        <p className="text-xs text-muted-foreground">
                                            Calls will only be made during this window. Leave empty for 24/7.
                                        </p>
                                        <div className="flex items-end gap-3 flex-wrap">
                                            <DetailTimePicker value={editWindowStart || '09:00'} onChange={setEditWindowStart} label="Start" />
                                            <span className="text-muted-foreground pb-2">to</span>
                                            <DetailTimePicker value={editWindowEnd || '17:00'} onChange={setEditWindowEnd} label="End" />
                                            {(editWindowStart || editWindowEnd) && (
                                                <Button
                                                    type="button"
                                                    variant="ghost"
                                                    size="sm"
                                                    className="text-xs text-muted-foreground h-9"
                                                    onClick={() => { setEditWindowStart(''); setEditWindowEnd(''); }}
                                                >
                                                    Clear
                                                </Button>
                                            )}
                                        </div>
                                        <div className="space-y-1">
                                            <Label className="text-xs">Timezone</Label>
                                            <Select value={editWindowTz} onValueChange={setEditWindowTz}>
                                                <SelectTrigger className="w-64">
                                                    <SelectValue />
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

                                    <div className="pt-2">
                                        <Button onClick={handleSaveSchedule} disabled={isSavingSchedule}>
                                            {isSavingSchedule ? (
                                                <>
                                                    <Spinner size="sm" className="mr-2" />
                                                    Saving...
                                                </>
                                            ) : (
                                                'Save Schedule'
                                            )}
                                        </Button>
                                    </div>
                                </div>
                            ) : (
                                <div className="text-sm text-muted-foreground">
                                    Schedule can only be edited when the campaign is in &quot;created&quot; or &quot;scheduled&quot; state.
                                    Current state: <Badge variant={getStateBadgeVariant(campaign.state)} className="ml-1">{campaign.state}</Badge>
                                </div>
                            )}
                        </CardContent>
                    </Card>
                </TabsContent>
            </Tabs>
        </div>
    );
}
