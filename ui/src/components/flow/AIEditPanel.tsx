import { ArrowUp, Check, GripHorizontal, X } from 'lucide-react';

import { Spinner } from '@/components/ui/ai-loader';
import { useCallback, useEffect, useRef, useState } from 'react';

import { getBackendUrl } from '@/lib/apiClient';
import { cn } from '@/lib/utils';

interface AIEditPanelProps {
    isOpen: boolean;
    onClose: () => void;
    workflowId: number;
    getAccessToken: () => Promise<string>;
    onApply: (result: { nodes: any[]; edges: any[]; explanation: string }) => void;
    currentNodes: any[];
    currentEdges: any[];
    currentViewport: { x: number; y: number; zoom: number };
}

export default function AIEditPanel({
    isOpen,
    onClose,
    workflowId,
    getAccessToken,
    onApply,
    currentNodes,
    currentEdges,
    currentViewport,
}: AIEditPanelProps) {
    const [instruction, setInstruction] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [status, setStatus] = useState<'idle' | 'success' | 'error'>('idle');
    const [statusMessage, setStatusMessage] = useState('');
    const inputRef = useRef<HTMLTextAreaElement>(null);

    const [position, setPosition] = useState<{ x: number; y: number } | null>(null);
    const isDragging = useRef(false);
    const dragOffset = useRef({ x: 0, y: 0 });
    const panelRef = useRef<HTMLDivElement>(null);

    const handlePointerDown = useCallback((e: React.PointerEvent) => {
        if (!panelRef.current) return;
        e.preventDefault();
        isDragging.current = true;

        const rect = panelRef.current.getBoundingClientRect();
        dragOffset.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };

        if (!position) {
            setPosition({ x: rect.left, y: rect.top });
        }

        (e.target as HTMLElement).setPointerCapture(e.pointerId);
    }, [position]);

    const handlePointerMove = useCallback((e: React.PointerEvent) => {
        if (!isDragging.current) return;

        const newX = Math.max(0, Math.min(e.clientX - dragOffset.current.x, window.innerWidth - 560));
        const newY = Math.max(0, Math.min(e.clientY - dragOffset.current.y, window.innerHeight - 80));
        setPosition({ x: newX, y: newY });
    }, []);

    const handlePointerUp = useCallback(() => {
        isDragging.current = false;
    }, []);

    useEffect(() => {
        if (isOpen) {
            setTimeout(() => inputRef.current?.focus(), 150);
            setStatus('idle');
            setStatusMessage('');
        } else {
            setPosition(null);
        }
    }, [isOpen]);

    useEffect(() => {
        if (status !== 'idle') {
            const t = setTimeout(() => {
                setStatus('idle');
                setStatusMessage('');
            }, 4000);
            return () => clearTimeout(t);
        }
    }, [status]);

    const handleSubmit = useCallback(async () => {
        if (!instruction.trim() || isLoading) return;

        setIsLoading(true);
        setStatus('idle');
        setStatusMessage('');

        try {
            const token = await getAccessToken();
            const response = await fetch(`${getBackendUrl()}/api/v1/workflow/${workflowId}/ai-edit`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`,
                },
                body: JSON.stringify({
                    instruction: instruction.trim(),
                    current_nodes: currentNodes,
                    current_edges: currentEdges,
                    current_viewport: currentViewport,
                }),
            });

            if (!response.ok) {
                const errData = await response.json().catch(() => ({}));
                throw new Error(errData.detail || 'Failed to edit workflow');
            }

            const result = await response.json();
            onApply({
                nodes: result.nodes,
                edges: result.edges,
                explanation: result.explanation,
            });
            setInstruction('');
            setStatus('success');
            setStatusMessage(result.explanation || 'Changes applied');
        } catch (err: any) {
            setStatus('error');
            setStatusMessage(err.message || 'Something went wrong');
        } finally {
            setIsLoading(false);
        }
    }, [instruction, isLoading, workflowId, getAccessToken, currentNodes, currentEdges, currentViewport, onApply]);

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSubmit();
        }
        if (e.key === 'Escape') {
            onClose();
        }
    };

    const positionStyle = position
        ? { left: position.x, top: position.y, transform: 'none', bottom: 'auto' }
        : {};

    return (
        <div
            ref={panelRef}
            className={cn(
                "fixed z-50 w-[560px] max-w-[calc(100vw-3rem)]",
                !position && "bottom-6 left-1/2 -translate-x-1/2",
                isDragging.current ? "" : "transition-all duration-200 ease-out",
                isOpen
                    ? "opacity-100 pointer-events-auto scale-100"
                    : "translate-y-4 opacity-0 pointer-events-none scale-[0.98]"
            )}
            style={positionStyle}
        >
            {/* Status toast */}
            {status !== 'idle' && (
                <div className={cn(
                    "mb-2 flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-medium transition-all duration-200 animate-in fade-in slide-in-from-bottom-2",
                    status === 'success'
                        ? "bg-emerald-950/80 text-emerald-300 border border-emerald-800/50"
                        : "bg-rose-950/80 text-rose-300 border border-rose-800/50"
                )}>
                    {status === 'success' ? <Check className="h-3 w-3 flex-shrink-0" /> : <X className="h-3 w-3 flex-shrink-0" />}
                    <span className="truncate">{statusMessage}</span>
                </div>
            )}

            {/* Input bar */}
            <div className="relative rounded-2xl border border-white/[0.08] bg-[#0c0c0c]/95 backdrop-blur-xl shadow-[0_8px_40px_rgba(0,0,0,0.5),0_0_0_1px_rgba(255,255,255,0.03)]">
                {isLoading && (
                    <div className="absolute inset-x-0 top-0 h-[2px] overflow-hidden rounded-t-2xl">
                        <div className="h-full w-1/3 bg-gradient-to-r from-transparent via-[#34F5C2] to-transparent animate-[shimmer_1.5s_ease-in-out_infinite]" />
                    </div>
                )}

                {/* Drag handle */}
                <div
                    onPointerDown={handlePointerDown}
                    onPointerMove={handlePointerMove}
                    onPointerUp={handlePointerUp}
                    className="flex items-center justify-center py-1 cursor-grab active:cursor-grabbing select-none touch-none"
                >
                    <GripHorizontal className="h-3.5 w-3.5 text-white/15" />
                </div>

                <div className="flex items-end gap-2 p-2 pt-0">
                    <textarea
                        ref={inputRef}
                        value={instruction}
                        onChange={(e) => setInstruction(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder="Edit workflow with AI..."
                        rows={1}
                        className={cn(
                            "flex-1 resize-none bg-transparent px-3 py-2.5 text-[13px] text-white/90",
                            "placeholder:text-white/25 focus:outline-none",
                            "min-h-[40px] max-h-[120px] leading-relaxed",
                        )}
                        disabled={isLoading}
                        style={{ fieldSizing: 'content' } as React.CSSProperties}
                    />

                    <div className="flex items-center gap-1.5 pb-1 pr-1">
                        <button
                            onClick={onClose}
                            className="flex h-7 w-7 items-center justify-center rounded-lg text-white/20 hover:text-white/50 hover:bg-white/[0.04] transition-colors"
                        >
                            <X className="h-3.5 w-3.5" />
                        </button>
                        <button
                            onClick={handleSubmit}
                            disabled={!instruction.trim() || isLoading}
                            className={cn(
                                "flex h-8 w-8 items-center justify-center rounded-xl transition-all duration-200",
                                instruction.trim() && !isLoading
                                    ? "bg-white text-black hover:bg-white/90 shadow-sm"
                                    : "bg-white/[0.06] text-white/20 cursor-not-allowed"
                            )}
                        >
                            {isLoading ? (
                                <Spinner size="sm" />
                            ) : (
                                <ArrowUp className="h-3.5 w-3.5" />
                            )}
                        </button>
                    </div>
                </div>

                {/* Subtle hint */}
                <div className="flex items-center gap-3 px-5 pb-2.5 -mt-0.5">
                    <span className="text-[10px] text-white/15 select-none">
                        <kbd className="px-1 py-0.5 rounded bg-white/[0.04] text-[9px] font-mono">Enter</kbd> to apply
                    </span>
                    <span className="text-[10px] text-white/15 select-none">
                        <kbd className="px-1 py-0.5 rounded bg-white/[0.04] text-[9px] font-mono">Esc</kbd> to close
                    </span>
                </div>
            </div>
        </div>
    );
}
