'use client';

import { addDays, format, isToday, subDays } from 'date-fns';
import {
  Calendar,
  ChevronLeft,
  ChevronRight,
  Download,
  LayoutDashboard,
} from 'lucide-react';

import { Spinner } from '@/components/ui/ai-loader';
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import {
  getDailyReportApiV1OrganizationsReportsDailyGet,
  getDailyRunsDetailApiV1OrganizationsReportsDailyRunsGet,
  getWorkflowOptionsApiV1OrganizationsReportsWorkflowsGet
} from '@/client/sdk.gen';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Calendar as CalendarPicker } from '@/components/ui/calendar';
import { Card, CardContent } from '@/components/ui/card';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useUserConfig } from '@/context/UserConfigContext';
import { useAuth } from '@/lib/auth';

import { DispositionChart } from './components/DispositionChart';
import { DurationChart } from './components/DurationChart';
import { MetricsCards } from './components/MetricsCards';

interface WorkflowOption {
  id: number;
  name: string;
}

interface DailyReport {
  date: string;
  timezone: string;
  workflow_id: number | null;
  metrics: {
    total_runs: number;
    xfer_count: number;
  };
  disposition_distribution: Array<{
    disposition: string;
    count: number;
    percentage: number;
  }>;
  call_duration_distribution: Array<{
    bucket: string;
    range_start: number;
    range_end: number | null;
    count: number;
    percentage: number;
  }>;
}

export default function ReportsPage() {
  const [selectedDate, setSelectedDate] = useState<Date>(new Date());
  const [selectedWorkflow, setSelectedWorkflow] = useState<string>('all');
  const [workflows, setWorkflows] = useState<WorkflowOption[]>([]);
  const [report, setReport] = useState<DailyReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isDownloading, setIsDownloading] = useState(false);
  const { userConfig } = useUserConfig();
  const { getAccessToken, isAuthenticated } = useAuth();

  const timezone = userConfig?.timezone || 'America/New_York';

  // Fetch workflows on mount
  useEffect(() => {
    const fetchWorkflows = async () => {
      if (!isAuthenticated) return;

      try {
        const accessToken = await getAccessToken();
        if (!accessToken) return;
        const response = await getWorkflowOptionsApiV1OrganizationsReportsWorkflowsGet({
          headers: {
            Authorization: `Bearer ${accessToken}`
          }
        });
        if (response.error) {
          console.error('Failed to fetch workflows:', response.error);
          return;
        }
        if (response.data) {
          setWorkflows(response.data);
        }
      } catch (err) {
        console.error('Failed to fetch workflows:', err);
      }
    };
    fetchWorkflows();
  }, [isAuthenticated, getAccessToken]);

  const fetchIdRef = useRef(0);

  const fetchReport = useCallback(async () => {
    if (!isAuthenticated) return;

    const currentFetchId = ++fetchIdRef.current;
    setLoading(true);
    setError(null);

    try {
      const accessToken = await getAccessToken();
      if (!accessToken) {
        if (currentFetchId === fetchIdRef.current) {
          setError('Not authenticated');
          setReport(null);
        }
        return;
      }
      const dateStr = format(selectedDate, 'yyyy-MM-dd');
      const workflowId = selectedWorkflow === 'all' ? undefined : parseInt(selectedWorkflow);

      const response = await getDailyReportApiV1OrganizationsReportsDailyGet({
        query: {
          date: dateStr,
          timezone,
          ...(workflowId && { workflow_id: workflowId })
        },
        headers: {
          Authorization: `Bearer ${accessToken}`
        }
      });

      if (currentFetchId !== fetchIdRef.current) return;

      if (response.error) {
        const detail = (response.error as { detail?: string })?.detail;
        setError(detail || 'Failed to load report data');
        setReport(null);
        return;
      }

      if (response.data) {
        setReport(response.data as DailyReport);
      } else {
        setReport(null);
        setError('No report data returned');
      }
    } catch (err) {
      if (currentFetchId !== fetchIdRef.current) return;
      console.error('Failed to fetch report:', err);
      setError('Failed to load report data');
      setReport(null);
    } finally {
      if (currentFetchId === fetchIdRef.current) {
        setLoading(false);
      }
    }
  }, [selectedDate, selectedWorkflow, timezone, isAuthenticated, getAccessToken]);

  // Fetch report data when date or workflow changes
  useEffect(() => {
    fetchReport();
  }, [fetchReport]);

  const handlePreviousDay = () => {
    setSelectedDate(subDays(selectedDate, 1));
  };

  const handleNextDay = () => {
    const next = addDays(selectedDate, 1);
    if (!isToday(selectedDate)) {
      setSelectedDate(next);
    }
  };

  const handleDownloadCSV = async () => {
    if (!isAuthenticated) return;
    setIsDownloading(true);

    try {
      const accessToken = await getAccessToken();
      if (!accessToken) {
        toast.error('Not authenticated');
        return;
      }
      const dateStr = format(selectedDate, 'yyyy-MM-dd');
      const workflowId = selectedWorkflow === 'all' ? undefined : parseInt(selectedWorkflow);

      const response = await getDailyRunsDetailApiV1OrganizationsReportsDailyRunsGet({
        query: {
          date: dateStr,
          timezone,
          ...(workflowId && { workflow_id: workflowId })
        },
        headers: {
          Authorization: `Bearer ${accessToken}`
        }
      });

      if (response.error) {
        const detail = (response.error as { detail?: string })?.detail;
        toast.error(detail || 'Failed to fetch CSV data');
        return;
      }

      if (response.data && response.data.length > 0) {
        const headers = ['Phone Number', 'Disposition', 'Duration (seconds)', 'Workflow Run URL'];
        const rows = response.data.map(run => {
          const url = `${window.location.origin}/workflow/${run.workflow_public_id ?? run.workflow_id}/run/${run.run_id}`;
          return [
            run.phone_number || '',
            run.disposition || '',
            run.duration_seconds.toString(),
            url
          ];
        });

        const csvContent = [
          headers.join(','),
          ...rows.map(row => row.map(cell => `"${cell}"`).join(','))
        ].join('\n');

        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement('a');
        const url = URL.createObjectURL(blob);

        const workflowName = selectedWorkflow === 'all'
          ? 'all_workflows'
          : workflows.find(w => w.id.toString() === selectedWorkflow)?.name?.replace(/\s+/g, '_') || 'workflow';

        link.setAttribute('href', url);
        link.setAttribute('download', `workflow_runs_${dateStr}_${workflowName}.csv`);
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      } else {
        toast.warning('No data available for download');
      }
    } catch (err) {
      console.error('Failed to download CSV:', err);
      toast.error('Failed to download CSV data');
    } finally {
      setIsDownloading(false);
    }
  };

  const isTodaySelected = isToday(selectedDate);
  const selectedWorkflowName = selectedWorkflow !== 'all'
    ? workflows.find(w => w.id.toString() === selectedWorkflow)?.name
    : null;

  return (
    <div className="container mx-auto p-4 sm:p-6 space-y-6 max-w-7xl">
      {/* Header Section */}
      <div className="flex flex-col gap-4">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-gradient-to-br from-primary/20 to-teal-500/20 border border-primary/20">
              <LayoutDashboard className="h-5 w-5 text-primary" />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight">Analytics</h1>
              <p className="text-sm text-muted-foreground/70">
                {isTodaySelected ? "Today's" : format(selectedDate, 'MMM dd, yyyy')} performance overview
              </p>
            </div>
          </div>

          {/* Controls Row */}
          <div className="flex flex-wrap gap-2 items-center">
            {/* Workflow Selector */}
            <Select value={selectedWorkflow} onValueChange={setSelectedWorkflow}>
              <SelectTrigger className="w-[180px] bg-white/[0.03] border-white/10 hover:bg-white/[0.06] transition-colors">
                <SelectValue placeholder="Select workflow" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Workflows</SelectItem>
                {workflows.map((workflow) => (
                  <SelectItem key={workflow.id} value={workflow.id.toString()}>
                    {workflow.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            {/* Date Navigation */}
            <div className="flex items-center bg-white/[0.03] border border-white/10 rounded-lg overflow-hidden">
              <Button
                variant="ghost"
                size="icon"
                onClick={handlePreviousDay}
                className="h-9 w-9 rounded-none hover:bg-white/[0.06]"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>

              <Popover>
                <PopoverTrigger asChild>
                  <Button
                    variant="ghost"
                    className="h-9 px-3 rounded-none font-medium hover:bg-white/[0.06] min-w-[140px]"
                  >
                    <Calendar className="mr-2 h-3.5 w-3.5 text-muted-foreground" />
                    {isTodaySelected ? 'Today' : format(selectedDate, 'MMM dd, yyyy')}
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-auto p-0" align="end">
                  <CalendarPicker
                    mode="single"
                    selected={selectedDate}
                    onSelect={(date) => date && setSelectedDate(date)}
                    disabled={(date) => date > new Date()}
                  />
                </PopoverContent>
              </Popover>

              <Button
                variant="ghost"
                size="icon"
                onClick={handleNextDay}
                disabled={isTodaySelected}
                className="h-9 w-9 rounded-none hover:bg-white/[0.06]"
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>

            {/* Download CSV */}
            {!loading && report && report.metrics.total_runs > 0 && (
              <Button
                variant="outline"
                size="sm"
                onClick={handleDownloadCSV}
                disabled={isDownloading}
                className="h-9 gap-1.5 bg-white/[0.03] border-white/10 hover:bg-white/[0.06]"
              >
                {isDownloading ? (
                  <Spinner size="sm" />
                ) : (
                  <Download className="h-3.5 w-3.5" />
                )}
                Export
              </Button>
            )}
          </div>
        </div>

        {/* Context Bar */}
        <div className="flex items-center gap-2 text-xs text-muted-foreground/50">
          <span>Timezone: {timezone}</span>
          {selectedWorkflowName && (
            <>
              <span>•</span>
              <Badge variant="secondary" className="text-xs font-normal bg-white/[0.05] text-muted-foreground/70 border-none">
                {selectedWorkflowName}
              </Badge>
            </>
          )}
        </div>
      </div>

      {/* Loading State */}
      {loading && (
        <div className="space-y-6">
          {/* Skeleton metrics */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <Card key={i} className="border-white/5 overflow-hidden">
                <CardContent className="p-5">
                  <div className="animate-pulse space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="h-3 w-20 bg-white/10 rounded" />
                      <div className="h-8 w-8 bg-white/10 rounded-lg" />
                    </div>
                    <div className="h-8 w-16 bg-white/10 rounded" />
                    <div className="h-2 w-28 bg-white/5 rounded" />
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
          {/* Skeleton charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {[...Array(2)].map((_, i) => (
              <Card key={i} className="border-white/5 overflow-hidden">
                <CardContent className="p-6">
                  <div className="animate-pulse space-y-4">
                    <div className="h-4 w-40 bg-white/10 rounded" />
                    <div className="h-3 w-28 bg-white/5 rounded" />
                    <div className="h-[260px] bg-white/[0.03] rounded-lg" />
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Error State */}
      {error && !loading && (
        <Card className="border-red-500/20 bg-red-500/5">
          <CardContent className="p-8 text-center">
            <div className="w-12 h-12 rounded-full bg-red-500/10 flex items-center justify-center mx-auto mb-3">
              <svg className="w-6 h-6 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
              </svg>
            </div>
            <p className="text-red-400 font-medium">{error}</p>
            <p className="text-sm text-muted-foreground/60 mt-1">Try refreshing or selecting a different date.</p>
            <Button
              variant="outline"
              size="sm"
              onClick={fetchReport}
              className="mt-3"
            >
              Retry
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Report Content */}
      {report && !loading && !error && (
        <>
          {/* Metrics Cards */}
          <MetricsCards metrics={report.metrics} />

          {/* Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <DispositionChart data={report.disposition_distribution} />
            <DurationChart data={report.call_duration_distribution} />
          </div>

          {/* Empty State */}
          {report.metrics.total_runs === 0 && (
            <Card className="border-white/5 bg-gradient-to-br from-white/[0.02] to-transparent">
              <CardContent className="py-16 text-center">
                <div className="w-16 h-16 rounded-full bg-muted/10 flex items-center justify-center mx-auto mb-4">
                  <svg className="w-8 h-8 text-muted-foreground/30" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M2.25 6.75c0 8.284 6.716 15 15 15h2.25a2.25 2.25 0 002.25-2.25v-1.372c0-.516-.351-.966-.852-1.091l-4.423-1.106c-.44-.11-.902.055-1.173.417l-.97 1.293c-.282.376-.769.542-1.21.38a12.035 12.035 0 01-7.143-7.143c-.162-.441.004-.928.38-1.21l1.293-.97c.363-.271.527-.734.417-1.173L6.963 3.102a1.125 1.125 0 00-1.091-.852H4.5A2.25 2.25 0 002.25 4.5v2.25z" />
                  </svg>
                </div>
                <p className="text-muted-foreground font-medium">
                  No calls found for {format(selectedDate, 'MMMM dd, yyyy')}
                </p>
                <p className="text-sm text-muted-foreground/50 mt-1">
                  {selectedWorkflowName
                    ? `No runs for "${selectedWorkflowName}" on this date.`
                    : 'Try selecting a different date or workflow.'}
                </p>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
