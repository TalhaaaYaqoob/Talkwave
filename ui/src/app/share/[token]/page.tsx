'use client';

import { Bot, Mic, MicOff, Phone, PhoneOff } from 'lucide-react';

import { Spinner } from '@/components/ui/ai-loader';
import { useParams } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { getBackendUrl } from '@/lib/apiClient';

interface TranscriptEntry {
    role: 'user' | 'assistant';
    content: string;
}

export default function SharePage() {
    const { token } = useParams<{ token: string }>();
    const [status, setStatus] = useState<'loading' | 'ready' | 'connecting' | 'connected' | 'ended' | 'error'>('loading');
    const [workflowName, setWorkflowName] = useState('Voice Agent');
    const [errorMessage, setErrorMessage] = useState('');
    const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
    const [isMuted, setIsMuted] = useState(false);
    const wsRef = useRef<WebSocket | null>(null);
    const pcRef = useRef<RTCPeerConnection | null>(null);
    const streamRef = useRef<MediaStream | null>(null);
    const scrollRef = useRef<HTMLDivElement>(null);

    const apiUrl = getBackendUrl();

    useEffect(() => {
        if (!token) return;
        (async () => {
            try {
                const configRes = await fetch(`${apiUrl}/api/v1/embed/config/${token}`);
                if (configRes.ok) {
                    const config = await configRes.json();
                    setWorkflowName(config.workflow_name || 'Voice Agent');
                }
                setStatus('ready');
            } catch {
                setStatus('error');
                setErrorMessage('This share link is invalid or has expired.');
            }
        })();
    }, [token, apiUrl]);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [transcript]);

    const startCall = useCallback(async () => {
        if (status !== 'ready') return;
        setStatus('connecting');
        setTranscript([]);

        try {
            const initRes = await fetch(`${apiUrl}/api/v1/embed/init`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token }),
            });

            if (!initRes.ok) {
                const errData = await initRes.json().catch(() => ({}));
                throw new Error(errData.detail || 'Failed to start session');
            }

            const { websocket_url } = await initRes.json();

            const ws = new WebSocket(websocket_url);
            wsRef.current = ws;

            ws.onopen = async () => {
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    streamRef.current = stream;

                    const pc = new RTCPeerConnection({
                        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
                    });
                    pcRef.current = pc;

                    stream.getTracks().forEach(t => pc.addTrack(t, stream));

                    pc.ontrack = (e) => {
                        const audio = new Audio();
                        audio.srcObject = e.streams[0];
                        audio.play().catch(() => {});
                    };

                    pc.onicecandidate = (e) => {
                        if (e.candidate && ws.readyState === WebSocket.OPEN) {
                            ws.send(JSON.stringify({ type: 'ice_candidate', candidate: e.candidate }));
                        }
                    };

                    const offer = await pc.createOffer();
                    await pc.setLocalDescription(offer);
                    ws.send(JSON.stringify({ type: 'offer', sdp: offer.sdp }));
                } catch (err: any) {
                    setStatus('error');
                    setErrorMessage('Microphone access required to test the voice agent.');
                }
            };

            ws.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);
                    if (msg.type === 'answer') {
                        pcRef.current?.setRemoteDescription({ type: 'answer', sdp: msg.sdp });
                        setStatus('connected');
                    } else if (msg.type === 'ice_candidate' && msg.candidate) {
                        pcRef.current?.addIceCandidate(msg.candidate);
                    } else if (msg.type === 'transcript') {
                        setTranscript(prev => [...prev, { role: msg.role, content: msg.content }]);
                    }
                } catch {}
            };

            ws.onclose = () => {
                // Read the live status via the functional updater so we don't
                // depend on the stale value captured when startCall ran.
                setStatus((prev) =>
                    prev === 'connected' || prev === 'connecting' ? 'ended' : prev,
                );
            };

            ws.onerror = () => {
                setStatus('error');
                setErrorMessage('Connection failed. Please try again.');
            };
        } catch (err: any) {
            setStatus('error');
            setErrorMessage(err.message || 'Something went wrong');
        }
    }, [status, token, apiUrl]);

    const endCall = useCallback(() => {
        streamRef.current?.getTracks().forEach(t => t.stop());
        pcRef.current?.close();
        wsRef.current?.close();
        pcRef.current = null;
        wsRef.current = null;
        streamRef.current = null;
        setStatus('ended');
    }, []);

    const toggleMute = useCallback(() => {
        if (streamRef.current) {
            const audioTrack = streamRef.current.getAudioTracks()[0];
            if (audioTrack) {
                audioTrack.enabled = !audioTrack.enabled;
                setIsMuted(!audioTrack.enabled);
            }
        }
    }, []);

    const restart = useCallback(() => {
        setStatus('ready');
        setTranscript([]);
        setErrorMessage('');
    }, []);

    return (
        <div className="min-h-screen bg-gradient-to-br from-gray-950 via-gray-900 to-gray-950 flex items-center justify-center p-4">
            <div className="w-full max-w-md">
                {/* Header */}
                <div className="text-center mb-8">
                    <div className="inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10 border border-primary/20 mb-4">
                        <Bot className="h-8 w-8 text-primary" />
                    </div>
                    <h1 className="text-2xl font-bold text-white">{workflowName}</h1>
                    <p className="text-sm text-muted-foreground mt-1">Test this voice agent</p>
                </div>

                {/* Main card */}
                <div className="rounded-2xl border border-white/10 bg-black/50 backdrop-blur-xl overflow-hidden">
                    {status === 'loading' && (
                        <div className="flex items-center justify-center py-16">
                            <Spinner size="lg" />
                        </div>
                    )}

                    {status === 'error' && (
                        <div className="p-8 text-center">
                            <div className="w-12 h-12 rounded-full bg-rose-500/10 flex items-center justify-center mx-auto mb-4">
                                <PhoneOff className="h-6 w-6 text-rose-400" />
                            </div>
                            <p className="text-sm text-rose-400 mb-4">{errorMessage}</p>
                            <Button onClick={restart} variant="outline" size="sm">Try Again</Button>
                        </div>
                    )}

                    {status === 'ready' && (
                        <div className="p-8 text-center">
                            <p className="text-sm text-muted-foreground mb-6">
                                Click below to start a voice conversation with the AI agent.
                            </p>
                            <Button
                                onClick={startCall}
                                size="lg"
                                className="rounded-full h-16 w-16 p-0 bg-emerald-600 hover:bg-emerald-500 shadow-lg shadow-emerald-600/30"
                            >
                                <Phone className="h-7 w-7" />
                            </Button>
                            <p className="text-xs text-muted-foreground mt-3">Microphone access required</p>
                        </div>
                    )}

                    {status === 'connecting' && (
                        <div className="p-8 text-center">
                            <div className="relative w-20 h-20 mx-auto mb-4">
                                <div className="absolute inset-0 rounded-full bg-primary/20 animate-ping" />
                                <div className="relative flex h-full w-full items-center justify-center rounded-full bg-primary/10 border border-primary/20">
                                    <Phone className="h-8 w-8 text-primary" />
                                </div>
                            </div>
                            <p className="text-sm text-muted-foreground">Connecting...</p>
                        </div>
                    )}

                    {(status === 'connected' || status === 'ended') && (
                        <>
                            {/* Transcript */}
                            <div ref={scrollRef} className="max-h-[50vh] overflow-y-auto p-4 space-y-3">
                                {transcript.length === 0 && status === 'connected' && (
                                    <p className="text-center text-xs text-muted-foreground py-4">
                                        Listening... Start speaking
                                    </p>
                                )}
                                {transcript.map((entry, i) => (
                                    <div key={i} className={`flex gap-2 ${entry.role === 'user' ? 'flex-row-reverse' : ''}`}>
                                        <div className={`flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs ${
                                            entry.role === 'user'
                                                ? 'bg-primary/10 text-primary border border-primary/20'
                                                : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                                        }`}>
                                            {entry.role === 'user' ? 'U' : 'A'}
                                        </div>
                                        <div className={`px-3 py-2 rounded-lg text-sm max-w-[80%] ${
                                            entry.role === 'user'
                                                ? 'bg-primary/10 text-[#d7fdf1]'
                                                : 'bg-white/5 text-gray-200'
                                        }`}>
                                            {entry.content}
                                        </div>
                                    </div>
                                ))}
                            </div>

                            {/* Controls */}
                            <div className="border-t border-white/10 p-4 flex items-center justify-center gap-3">
                                {status === 'connected' ? (
                                    <>
                                        <Button
                                            onClick={toggleMute}
                                            variant="outline"
                                            size="icon"
                                            className={`rounded-full h-12 w-12 ${isMuted ? 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400' : ''}`}
                                        >
                                            {isMuted ? <MicOff className="h-5 w-5" /> : <Mic className="h-5 w-5" />}
                                        </Button>
                                        <Button
                                            onClick={endCall}
                                            size="icon"
                                            className="rounded-full h-12 w-12 bg-rose-600 hover:bg-rose-500"
                                        >
                                            <PhoneOff className="h-5 w-5" />
                                        </Button>
                                    </>
                                ) : (
                                    <Button onClick={restart} variant="outline" size="sm">
                                        Start New Call
                                    </Button>
                                )}
                            </div>
                        </>
                    )}
                </div>

                {/* Footer */}
                <p className="text-center text-[10px] text-muted-foreground/50 mt-4">
                    Powered by Talkwave
                </p>
            </div>
        </div>
    );
}
