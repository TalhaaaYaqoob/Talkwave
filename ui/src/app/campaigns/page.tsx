"use client";

import { Pause, Play, Plus, RefreshCw, Trash2 } from 'lucide-react';

import { Spinner } from '@/components/ui/ai-loader';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import {
    getCampaignsApiV1CampaignGet,
    pauseCampaignApiV1CampaignCampaignIdPausePost,
    resumeCampaignApiV1CampaignCampaignIdResumePost,
    startCampaignApiV1CampaignCampaignIdStartPost,
} from '@/client/sdk.gen';
import type { CampaignsResponse } from '@/client/types.gen';
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table';
import { getBackendUrl } from '@/lib/apiClient';
import { useAuth } from '@/lib/auth';

export default function CampaignsPage() {
    const { user, getAccessToken, redirectToLogin, loading } = useAuth();
    const router = useRouter();

    const [campaignsData, setCampaignsData] = useState<CampaignsResponse | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [deletingId, setDeletingId] = useState<number | null>(null);
    const [actionId, setActionId] = useState<number | null>(null);
    const [deleteTarget, setDeleteTarget] = useState<{ id: number; name: string } | null>(null);

    useEffect(() => {
        if (!loading && !user) {
            redirectToLogin();
        }
    }, [loading, user, redirectToLogin]);

    const fetchCampaigns = useCallback(async (silent = false) => {
        if (!user) return;
        try {
            if (!silent) setIsLoading(true);
            const accessToken = await getAccessToken();
            const response = await getCampaignsApiV1CampaignGet({
                headers: { 'Authorization': `Bearer ${accessToken}` },
            });
            if (response.data) {
                setCampaignsData(response.data);
            }
        } catch (error) {
            console.error('Failed to fetch campaigns:', error);
        } finally {
            setIsLoading(false);
        }
    }, [user, getAccessToken]);

    useEffect(() => {
        if (user) fetchCampaigns();
    }, [user, fetchCampaigns]);

    // Auto-refresh every 5s when any campaign is active
    const autoRefreshRef = useRef<ReturnType<typeof setInterval> | null>(null);
    useEffect(() => {
        const hasActive = campaignsData?.campaigns.some(
            (c) => c.state === 'running' || c.state === 'syncing' || c.state === 'scheduled'
        );
        if (hasActive) {
            autoRefreshRef.current = setInterval(() => fetchCampaigns(true), 5000);
        }
        return () => {
            if (autoRefreshRef.current) clearInterval(autoRefreshRef.current);
        };
    }, [campaignsData, fetchCampaigns]);

    const handleRowClick = (campaignId: number) => {
        router.push(`/campaigns/${campaignId}`);
    };

    const handleStart = async (e: React.MouseEvent, campaignId: number) => {
        e.stopPropagation();
        setActionId(campaignId);
        try {
            const accessToken = await getAccessToken();
            const response = await startCampaignApiV1CampaignCampaignIdStartPost({
                path: { campaign_id: campaignId },
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            if (response.data) {
                toast.success(
                    response.data.state === 'scheduled'
                        ? 'Campaign scheduled'
                        : 'Campaign started'
                );
                fetchCampaigns(true);
            } else if (response.error) {
                const err = response.error as { detail?: { error?: string; message?: string } | string };
                if (typeof err?.detail === 'object' && err.detail?.error === 'subscription_limit') {
                    toast.error(err.detail.message || 'Subscription limit reached');
                    router.push('/usage');
                    return;
                }
                const msg = typeof err?.detail === 'string' ? err.detail : 'Failed to start campaign';
                toast.error(msg);
            }
        } catch {
            toast.error('Failed to start campaign');
        } finally {
            setActionId(null);
        }
    };

    const handlePause = async (e: React.MouseEvent, campaignId: number) => {
        e.stopPropagation();
        setActionId(campaignId);
        try {
            const accessToken = await getAccessToken();
            const response = await pauseCampaignApiV1CampaignCampaignIdPausePost({
                path: { campaign_id: campaignId },
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            if (response.data) {
                toast.success('Campaign paused');
                fetchCampaigns(true);
            } else {
                toast.error('Failed to pause campaign');
            }
        } catch {
            toast.error('Failed to pause campaign');
        } finally {
            setActionId(null);
        }
    };

    const handleResume = async (e: React.MouseEvent, campaignId: number) => {
        e.stopPropagation();
        setActionId(campaignId);
        try {
            const accessToken = await getAccessToken();
            const response = await resumeCampaignApiV1CampaignCampaignIdResumePost({
                path: { campaign_id: campaignId },
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            if (response.data) {
                toast.success('Campaign resumed');
                fetchCampaigns(true);
            } else if (response.error) {
                const err = response.error as { detail?: { error?: string; message?: string } | string };
                if (typeof err?.detail === 'object' && err.detail?.error === 'subscription_limit') {
                    toast.error(err.detail.message || 'Subscription limit reached');
                    router.push('/usage');
                    return;
                }
                toast.error('Failed to resume campaign');
            }
        } catch {
            toast.error('Failed to resume campaign');
        } finally {
            setActionId(null);
        }
    };

    const handleDeleteClick = (e: React.MouseEvent, campaignId: number, campaignName: string) => {
        e.stopPropagation();
        setDeleteTarget({ id: campaignId, name: campaignName });
    };

    const handleDeleteConfirm = async () => {
        if (!deleteTarget) return;
        const campaignId = deleteTarget.id;
        setDeleteTarget(null);
        setDeletingId(campaignId);
        try {
            const accessToken = await getAccessToken();
            const baseUrl = getBackendUrl();
            const res = await fetch(`${baseUrl}/api/v1/campaign/${campaignId}`, {
                method: 'DELETE',
                headers: { Authorization: `Bearer ${accessToken}` },
            });
            if (res.ok) {
                toast.success('Campaign deleted');
                fetchCampaigns(true);
            } else {
                const error = await res.json();
                toast.error(error.detail || 'Failed to delete campaign');
            }
        } catch {
            toast.error('Failed to delete campaign');
        } finally {
            setDeletingId(null);
        }
    };

    const handleCreateCampaign = () => {
        router.push('/campaigns/new');
    };

    const formatDate = (dateString: string) => {
        return new Date(dateString).toLocaleDateString();
    };

    const getStateBadgeVariant = (state: string) => {
        switch (state) {
            case 'created':
                return 'secondary';
            case 'scheduled':
                return 'outline';
            case 'running':
            case 'syncing':
                return 'default';
            case 'paused':
                return 'outline';
            case 'completed':
                return 'secondary';
            case 'failed':
                return 'destructive';
            default:
                return 'secondary';
        }
    };

    const renderCampaignActions = (campaign: CampaignsResponse['campaigns'][number]) => {
        const isBusy = actionId === campaign.id || deletingId === campaign.id;

        return (
            <div className="flex items-center justify-end gap-1">
                {campaign.state === 'created' && (
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-muted-foreground hover:text-green-500"
                        disabled={isBusy}
                        onClick={(e) => handleStart(e, campaign.id)}
                        title="Start campaign"
                    >
                        {actionId === campaign.id ? (
                            <Spinner size="sm" />
                        ) : (
                            <Play className="h-4 w-4" />
                        )}
                    </Button>
                )}
                {(campaign.state === 'running' || campaign.state === 'syncing' || campaign.state === 'scheduled') && (
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-muted-foreground hover:text-yellow-500"
                        disabled={isBusy}
                        onClick={(e) => handlePause(e, campaign.id)}
                        title={campaign.state === 'scheduled' ? 'Cancel scheduled campaign' : 'Pause campaign'}
                    >
                        {actionId === campaign.id ? (
                            <Spinner size="sm" />
                        ) : (
                            <Pause className="h-4 w-4" />
                        )}
                    </Button>
                )}
                {campaign.state === 'paused' && (
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-muted-foreground hover:text-green-500"
                        disabled={isBusy}
                        onClick={(e) => handleResume(e, campaign.id)}
                        title="Resume campaign"
                    >
                        {actionId === campaign.id ? (
                            <Spinner size="sm" />
                        ) : (
                            <RefreshCw className="h-4 w-4" />
                        )}
                    </Button>
                )}
                {campaign.state !== 'running' && (
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-muted-foreground hover:text-destructive"
                        disabled={isBusy}
                        onClick={(e) => handleDeleteClick(e, campaign.id, campaign.name)}
                        title="Delete campaign"
                    >
                        {deletingId === campaign.id ? (
                            <Spinner size="sm" />
                        ) : (
                            <Trash2 className="h-4 w-4" />
                        )}
                    </Button>
                )}
            </div>
        );
    };

    const renderMobileActions = (campaign: CampaignsResponse['campaigns'][number]) => {
        const isBusy = actionId === campaign.id || deletingId === campaign.id;

        return (
            <div className="flex items-center gap-1">
                {campaign.state === 'created' && (
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-green-500"
                        disabled={isBusy}
                        onClick={(e) => handleStart(e, campaign.id)}
                    >
                        {actionId === campaign.id ? (
                            <Spinner size="sm" />
                        ) : (
                            <Play className="h-3.5 w-3.5" />
                        )}
                    </Button>
                )}
                {(campaign.state === 'running' || campaign.state === 'syncing' || campaign.state === 'scheduled') && (
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-yellow-500"
                        disabled={isBusy}
                        onClick={(e) => handlePause(e, campaign.id)}
                    >
                        {actionId === campaign.id ? (
                            <Spinner size="sm" />
                        ) : (
                            <Pause className="h-3.5 w-3.5" />
                        )}
                    </Button>
                )}
                {campaign.state === 'paused' && (
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-green-500"
                        disabled={isBusy}
                        onClick={(e) => handleResume(e, campaign.id)}
                    >
                        {actionId === campaign.id ? (
                            <Spinner size="sm" />
                        ) : (
                            <RefreshCw className="h-3.5 w-3.5" />
                        )}
                    </Button>
                )}
                {campaign.state !== 'running' && (
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-destructive"
                        disabled={isBusy}
                        onClick={(e) => handleDeleteClick(e, campaign.id, campaign.name)}
                    >
                        {deletingId === campaign.id ? (
                            <Spinner size="sm" />
                        ) : (
                            <Trash2 className="h-3.5 w-3.5" />
                        )}
                    </Button>
                )}
            </div>
        );
    };

    return (
        <div className="container mx-auto p-4 sm:p-6 space-y-4 sm:space-y-6">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                <div>
                    <h1 className="text-2xl sm:text-3xl font-bold mb-1 sm:mb-2">Campaigns</h1>
                    <p className="text-sm sm:text-base text-muted-foreground">Manage your bulk workflow execution campaigns</p>
                </div>
                <Button onClick={handleCreateCampaign} className="w-full sm:w-auto">
                    <Plus className="h-4 w-4 mr-2" />
                    Create Campaign
                </Button>
            </div>

            <Card>
                <CardHeader className="p-4 sm:p-6">
                    <CardTitle className="text-lg sm:text-xl">All Campaigns</CardTitle>
                    <CardDescription className="text-sm">
                        View and manage your campaigns
                    </CardDescription>
                </CardHeader>
                <CardContent className="p-4 sm:p-6 pt-0 sm:pt-0">
                    {isLoading ? (
                        <div className="animate-pulse space-y-3">
                            {[...Array(5)].map((_, i) => (
                                <div key={i} className="h-12 bg-muted rounded"></div>
                            ))}
                        </div>
                    ) : campaignsData && campaignsData.campaigns.length > 0 ? (
                        <>
                            {/* Mobile Card View */}
                            <div className="block sm:hidden space-y-3">
                                {campaignsData.campaigns.map((campaign) => (
                                    <div
                                        key={campaign.id}
                                        className="p-4 border rounded-lg cursor-pointer hover:bg-muted/50 transition-colors"
                                        onClick={() => handleRowClick(campaign.id)}
                                    >
                                        <div className="flex justify-between items-start mb-2">
                                            <span className="font-medium text-sm">{campaign.name}</span>
                                            <div className="flex items-center gap-1">
                                                <Badge variant={getStateBadgeVariant(campaign.state)} className="text-xs">
                                                    {campaign.state}
                                                </Badge>
                                                {renderMobileActions(campaign)}
                                            </div>
                                        </div>
                                        <div className="text-xs text-muted-foreground space-y-1">
                                            <p>Workflow: {campaign.workflow_name}</p>
                                            <p>Created: {formatDate(campaign.created_at)}</p>
                                            {(campaign.total_rows ?? 0) > 0 && (
                                                <p>Progress: {campaign.processed_rows}/{campaign.total_rows}</p>
                                            )}
                                            {(campaign.completed_calls ?? 0) > 0 && (
                                                <p>Connected: <span className="text-green-400 font-medium">{campaign.completed_calls}</span></p>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                            {/* Desktop Table View */}
                            <div className="hidden sm:block overflow-x-auto">
                                <Table>
                                    <TableHeader>
                                        <TableRow>
                                            <TableHead>Name</TableHead>
                                            <TableHead>Workflow</TableHead>
                                            <TableHead>State</TableHead>
                                            <TableHead>Progress</TableHead>
                                            <TableHead>Connected</TableHead>
                                            <TableHead>Created</TableHead>
                                            <TableHead className="text-right">Actions</TableHead>
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {campaignsData.campaigns.map((campaign) => (
                                            <TableRow
                                                key={campaign.id}
                                                className="cursor-pointer hover:bg-muted/50"
                                                onClick={() => handleRowClick(campaign.id)}
                                            >
                                                <TableCell className="font-medium">{campaign.name}</TableCell>
                                                <TableCell>{campaign.workflow_name}</TableCell>
                                                <TableCell>
                                                    <Badge variant={getStateBadgeVariant(campaign.state)}>
                                                        {campaign.state}
                                                    </Badge>
                                                </TableCell>
                                                <TableCell>
                                                    {(campaign.total_rows ?? 0) > 0 ? (
                                                        <span className="text-xs text-muted-foreground">
                                                            {campaign.processed_rows}/{campaign.total_rows}
                                                            {campaign.failed_rows > 0 && (
                                                                <span className="text-red-400 ml-1">({campaign.failed_rows} failed)</span>
                                                            )}
                                                        </span>
                                                    ) : (
                                                        <span className="text-xs text-muted-foreground">-</span>
                                                    )}
                                                </TableCell>
                                                <TableCell>
                                                    {(campaign.completed_calls ?? 0) > 0 ? (
                                                        <span className="text-xs font-medium text-green-400">
                                                            {campaign.completed_calls}
                                                        </span>
                                                    ) : (
                                                        <span className="text-xs text-muted-foreground">-</span>
                                                    )}
                                                </TableCell>
                                                <TableCell>{formatDate(campaign.created_at)}</TableCell>
                                                <TableCell className="text-right">
                                                    {renderCampaignActions(campaign)}
                                                </TableCell>
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            </div>
                        </>
                    ) : (
                        <div className="text-center py-8">
                            <p className="mb-4 text-sm sm:text-base">No campaigns found</p>
                            <Button onClick={handleCreateCampaign} variant="outline" className="w-full sm:w-auto">
                                <Plus className="h-4 w-4 mr-2" />
                                Create your first campaign
                            </Button>
                        </div>
                    )}
                </CardContent>
            </Card>

            <AlertDialog open={!!deleteTarget} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Delete Campaign</AlertDialogTitle>
                        <AlertDialogDescription>
                            Are you sure you want to delete &quot;{deleteTarget?.name}&quot;? This action cannot be undone and all associated data will be permanently removed.
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction
                            onClick={handleDeleteConfirm}
                            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                        >
                            Delete
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>
    );
}
