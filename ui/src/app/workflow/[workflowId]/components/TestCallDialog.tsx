"use client";

import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Clock, Mic, Phone, PhoneOff, X } from "lucide-react";

import { Spinner } from "@/components/ui/ai-loader";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { createWorkflowRunApiV1WorkflowWorkflowIdRunsPost } from "@/client/sdk.gen";
import { getBackendUrl } from "@/lib/apiClient";
import { Button } from "@/components/ui/button";
import { WORKFLOW_RUN_MODES } from "@/constants/workflowRunModes";

import { useWebSocketRTC } from "../run/[runId]/hooks/useWebSocketRTC";
import { useLiveKitRTC } from "../run/[runId]/hooks/useLiveKitRTC";
import { LiveTranscript } from "../run/[runId]/components/LiveTranscript";

interface TestCallDialogProps {
    open: boolean;
    onClose: () => void;
    workflowId: number;
    getAccessToken: () => Promise<string>;
}

function CallTimer({ startTime }: { startTime: number | null }) {
    const [elapsed, setElapsed] = useState(0);
    useEffect(() => {
        if (!startTime) { setElapsed(0); return; }
        const tick = () => setElapsed(Math.floor((Date.now() - startTime) / 1000));
        tick();
        const id = setInterval(tick, 1000);
        return () => clearInterval(id);
    }, [startTime]);
    const mins = Math.floor(elapsed / 60);
    const secs = elapsed % 60;
    return <span className="tabular-nums">{mins}:{secs.toString().padStart(2, '0')}</span>;
}

function useTransportHook(
    useLiveKit: boolean,
    props: { workflowId: number; workflowRunId: number; accessToken: string | null; initialContextVariables?: Record<string, string> | null },
) {
    const wsHook = useWebSocketRTC(props);
    const lkHook = useLiveKitRTC(props);
    return useLiveKit ? lkHook : wsHook;
}

export function TestCallDialog({ open, onClose, workflowId, getAccessToken }: TestCallDialogProps) {
    const [phase, setPhase] = useState<'idle' | 'creating' | 'active' | 'ended'>('idle');
    const [runId, setRunId] = useState<number | null>(null);
    const [accessToken, setAccessToken] = useState<string | null>(null);
    const [useLiveKit, setUseLiveKit] = useState(false);
    const [callStartTime, setCallStartTime] = useState<number | null>(null);

    useEffect(() => {
        if (!open) return;
        (async () => {
            try {
                let backendUrl = getBackendUrl();
                if (!backendUrl || backendUrl === '/') backendUrl = 'http://127.0.0.1:8000';
                backendUrl = backendUrl.replace(/\/$/, '');
                const res = await fetch(`${backendUrl}/api/v1/livekit/config`);
                if (res.ok) {
                    const data = await res.json();
                    if (data.enabled) setUseLiveKit(true);
                }
            } catch { /* fallback to WebRTC */ }
        })();
    }, [open]);

    const startCall = useCallback(async () => {
        setPhase('creating');
        try {
            const token = await getAccessToken();
            setAccessToken(token);

            const response = await createWorkflowRunApiV1WorkflowWorkflowIdRunsPost({
                path: { workflow_id: workflowId },
                body: { mode: WORKFLOW_RUN_MODES.SMALL_WEBRTC, name: `WR-${Math.floor(Math.random() * 10_000)}` },
                headers: { 'Authorization': `Bearer ${token}` },
            });

            if (response.error) {
                const errorDetail = response.error as { detail?: { message?: string } };
                toast.error(errorDetail?.detail?.message || 'Failed to start test call');
                setPhase('idle');
                return;
            }

            if (response.data?.id) {
                setRunId(response.data.id);
                setPhase('active');
            }
        } catch {
            toast.error('Failed to start test call. Please try again.');
            setPhase('idle');
        }
    }, [workflowId, getAccessToken]);

    const handleClose = useCallback(() => {
        setPhase('idle');
        setRunId(null);
        setAccessToken(null);
        setCallStartTime(null);
        onClose();
    }, [onClose]);

    if (!open) return null;

    return (
        <AnimatePresence>
            {open && (
                <motion.div
                    className="fixed inset-0 z-[200] flex items-center justify-end"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                >
                    {/* Backdrop */}
                    <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={handleClose} />

                    {/* Panel - slides in from right */}
                    <motion.div
                        className="relative h-full w-full max-w-md border-l border-white/10 bg-[#0a0a0a] shadow-2xl flex flex-col"
                        initial={{ x: '100%' }}
                        animate={{ x: 0 }}
                        exit={{ x: '100%' }}
                        transition={{ type: 'spring', damping: 30, stiffness: 300 }}
                    >
                        {/* Header */}
                        <div className="flex items-center justify-between px-5 py-4 border-b border-white/[0.06]">
                            <div className="flex items-center gap-3">
                                <div className={`w-9 h-9 rounded-full flex items-center justify-center ${
                                    phase === 'active' ? 'bg-emerald-500/15 text-emerald-400' :
                                    phase === 'creating' ? 'bg-amber-500/15 text-amber-400' :
                                    'bg-white/5 text-muted-foreground'
                                }`}>
                                    {phase === 'creating' && <Spinner size="sm" />}
                                    {phase === 'active' && <Mic className="h-4 w-4" />}
                                    {(phase === 'idle' || phase === 'ended') && <Phone className="h-4 w-4" />}
                                </div>
                                <div>
                                    <h2 className="text-sm font-semibold text-white">
                                        {phase === 'idle' && 'Test Call'}
                                        {phase === 'creating' && 'Connecting...'}
                                        {phase === 'active' && 'Call Active'}
                                        {phase === 'ended' && 'Call Ended'}
                                    </h2>
                                    <p className="text-[11px] text-muted-foreground">
                                        {phase === 'idle' && 'Start a test call to your agent'}
                                        {phase === 'creating' && 'Setting up audio...'}
                                        {phase === 'active' && callStartTime && (
                                            <span className="flex items-center gap-1">
                                                <Clock className="h-3 w-3" />
                                                <CallTimer startTime={callStartTime} />
                                            </span>
                                        )}
                                        {phase === 'ended' && 'Call completed'}
                                    </p>
                                </div>
                            </div>
                            <button
                                onClick={handleClose}
                                className="flex h-8 w-8 items-center justify-center rounded-lg text-white/30 hover:text-white/70 hover:bg-white/5 transition-colors"
                            >
                                <X className="h-4 w-4" />
                            </button>
                        </div>

                        {/* Content */}
                        <div className="flex-1 overflow-hidden flex flex-col">
                            {phase === 'idle' && (
                                <div className="flex-1 flex flex-col items-center justify-center gap-6 px-8">
                                    <div className="w-20 h-20 rounded-full bg-primary/10 border border-primary/20 flex items-center justify-center">
                                        <Phone className="h-8 w-8 text-primary" />
                                    </div>
                                    <div className="text-center">
                                        <p className="text-sm text-white font-medium">Ready to test</p>
                                        <p className="text-xs text-muted-foreground mt-1 max-w-[240px]">
                                            Start a voice call to test your agent right here. Iterate on the flow and test again — no navigation needed.
                                        </p>
                                    </div>
                                    <Button
                                        onClick={startCall}
                                        className="rounded-full h-12 px-8 bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-600/20 font-medium"
                                    >
                                        <Phone className="h-4 w-4 mr-2" />
                                        Start Test Call
                                    </Button>
                                </div>
                            )}

                            {phase === 'creating' && (
                                <div className="flex-1 flex flex-col items-center justify-center gap-4">
                                    <div className="relative w-16 h-16">
                                        <div className="absolute inset-0 rounded-full bg-primary/20 animate-ping" style={{ animationDuration: '2s' }} />
                                        <div className="relative flex h-full w-full items-center justify-center rounded-full bg-primary/10 border border-primary/20">
                                            <Spinner size="lg" />
                                        </div>
                                    </div>
                                    <p className="text-sm text-muted-foreground">Connecting to agent...</p>
                                </div>
                            )}

                            {(phase === 'active' || phase === 'ended') && runId && accessToken && (
                                <ActiveCallContent
                                    workflowId={workflowId}
                                    runId={runId}
                                    accessToken={accessToken}
                                    useLiveKit={useLiveKit}
                                    phase={phase}
                                    onCallStart={() => setCallStartTime(Date.now())}
                                    onCallEnd={() => setPhase('ended')}
                                    onNewCall={() => {
                                        setPhase('idle');
                                        setRunId(null);
                                        setCallStartTime(null);
                                    }}
                                />
                            )}
                        </div>
                    </motion.div>
                </motion.div>
            )}
        </AnimatePresence>
    );
}

interface ActiveCallContentProps {
    workflowId: number;
    runId: number;
    accessToken: string;
    useLiveKit: boolean;
    phase: 'active' | 'ended';
    onCallStart: () => void;
    onCallEnd: () => void;
    onNewCall: () => void;
}

function ActiveCallContent({
    workflowId, runId, accessToken, useLiveKit,
    phase, onCallStart, onCallEnd, onNewCall
}: ActiveCallContentProps) {
    const calledStart = useRef(false);

    const {
        audioRef,
        connectionActive,
        agentHasSpoken,
        isCompleted,
        start,
        stop,
        transcriptMessages,
        userInterim,
        assistantInterim,
    } = useTransportHook(useLiveKit, { workflowId, workflowRunId: runId, accessToken });

    useEffect(() => {
        if (!calledStart.current) {
            calledStart.current = true;
            start();
        }
    }, [start]);

    useEffect(() => {
        if (connectionActive && agentHasSpoken) {
            onCallStart();
        }
    }, [connectionActive, agentHasSpoken, onCallStart]);

    useEffect(() => {
        if (isCompleted) {
            onCallEnd();
        }
    }, [isCompleted, onCallEnd]);

    const handleStop = useCallback(() => {
        stop();
        onCallEnd();
    }, [stop, onCallEnd]);

    return (
        <>
            {/* Transcript area */}
            <div className="flex-1 overflow-hidden">
                <LiveTranscript
                    messages={transcriptMessages}
                    isActive={connectionActive}
                    userInterim={userInterim}
                    assistantInterim={assistantInterim}
                    workflowId={workflowId}
                    accessToken={accessToken}
                />
            </div>

            {/* Bottom controls */}
            <div className="border-t border-white/[0.06] px-5 py-4">
                {phase === 'active' && !isCompleted ? (
                    <div className="flex items-center justify-center">
                        <Button
                            size="icon"
                            onClick={handleStop}
                            className="rounded-full h-12 w-12 bg-rose-600 hover:bg-rose-500 text-white shadow-lg"
                        >
                            <PhoneOff className="h-5 w-5" />
                        </Button>
                    </div>
                ) : (
                    <div className="flex flex-col items-center gap-3">
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                            <span>{transcriptMessages.length} messages</span>
                        </div>
                        <Button
                            onClick={onNewCall}
                            className="rounded-full h-10 px-6 bg-white/5 border border-white/10 hover:bg-white/10 text-white text-sm"
                        >
                            <Phone className="h-3.5 w-3.5 mr-2" />
                            New Test Call
                        </Button>
                    </div>
                )}
            </div>

            <audio ref={audioRef} autoPlay playsInline className="hidden" />
        </>
    );
}
