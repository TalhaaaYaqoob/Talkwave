import { Position, useReactFlow } from "@xyflow/react";
import { Copy, Edit, Trash2 } from "lucide-react";
import { MouseEvent, ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { BaseHandle } from "@/components/flow/nodes/BaseHandle";
import { BaseNode } from "@/components/flow/nodes/BaseNode";
import { cn } from "@/lib/utils";

interface NodeContentProps {
    selected: boolean;
    invalid?: boolean;
    selected_through_edge?: boolean;
    hovered_through_edge?: boolean;
    title: string;
    icon: ReactNode;
    nodeType?: 'start' | 'agent' | 'end' | 'global' | 'action' | 'callVariables' | 'ifelse' | 'categorize' | 'transfer' | 'meetingTrigger' | 'meetingSummary';
    hasSourceHandle?: boolean;
    hasTargetHandle?: boolean;
    children?: ReactNode;
    className?: string;
    onDoubleClick?: () => void;
    onEdit?: () => void;
    nodeId?: string;
    preventDelete?: boolean;
    sourceHandleIds?: string[];
}

// Get badge styling based on node type
const getNodeTypeBadge = (nodeType?: string) => {
    switch (nodeType) {
        case 'start':
            return { label: 'Start', className: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40 shadow-[0_0_10px_rgba(52,211,153,0.1)]' };
        case 'agent':
            return { label: 'Agent', className: 'bg-primary/20 text-primary border-primary/40 shadow-[0_0_10px_rgba(52,245,194,0.12)]' };
        case 'end':
            return { label: 'End', className: 'bg-rose-500/20 text-rose-400 border-rose-500/40 shadow-[0_0_10px_rgba(251,113,133,0.1)]' };
        case 'global':
            return { label: 'Global', className: 'bg-amber-500/20 text-amber-400 border-amber-500/40 shadow-[0_0_10px_rgba(251,191,36,0.1)]' };
        case 'action':
            return { label: 'Action', className: 'bg-violet-500/20 text-violet-400 border-violet-500/40 shadow-[0_0_10px_rgba(167,139,250,0.1)]' };
        case 'callVariables':
            return { label: 'Call Variables', className: 'bg-indigo-500/20 text-indigo-400 border-indigo-500/40 shadow-[0_0_10px_rgba(129,140,248,0.1)]' };
        case 'ifelse':
            return { label: 'If / Else', className: 'bg-orange-500/20 text-orange-400 border-orange-500/40 shadow-[0_0_10px_rgba(251,146,60,0.1)]' };
        case 'categorize':
            return { label: 'Categorize', className: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/40 shadow-[0_0_10px_rgba(34,211,238,0.1)]' };
        case 'transfer':
            return { label: 'Transfer', className: 'bg-pink-500/20 text-pink-400 border-pink-500/40 shadow-[0_0_10px_rgba(236,72,153,0.1)]' };
        case 'meetingTrigger':
            return { label: 'Meeting Trigger', className: 'bg-violet-500/20 text-violet-400 border-violet-500/40 shadow-[0_0_10px_rgba(139,92,246,0.1)]' };
        case 'meetingSummary':
            return { label: 'Meeting Summary', className: 'bg-teal-500/20 text-teal-400 border-teal-500/40 shadow-[0_0_10px_rgba(20,184,166,0.1)]' };
        default:
            return { label: 'Node', className: 'bg-zinc-800 text-zinc-400 border-white/10' };
    }
};

// Context menu item component
const ContextMenuItem = ({
    onClick,
    icon: Icon,
    label,
    shortcut,
    variant = "default",
    disabled = false
}: {
    onClick: () => void;
    icon: React.ComponentType<{ className?: string }>;
    label: string;
    shortcut?: string;
    variant?: "default" | "destructive";
    disabled?: boolean;
}) => (
    <button
        onClick={(e) => {
            e.stopPropagation();
            e.preventDefault();
            if (!disabled) onClick();
        }}
        disabled={disabled}
        className={cn(
            "flex items-center w-full px-3 py-2 text-sm rounded-sm transition-colors",
            "hover:bg-accent focus:bg-accent focus:outline-none",
            variant === "destructive"
                ? "text-destructive hover:text-destructive focus:text-destructive"
                : "hover:text-accent-foreground focus:text-accent-foreground",
            disabled && "opacity-50 cursor-not-allowed"
        )}
    >
        <Icon className="mr-2 h-4 w-4" />
        <span>{label}</span>
        {shortcut && (
            <span className="ml-auto text-xs text-muted-foreground">{shortcut}</span>
        )}
    </button>
);

// Context Menu Portal Component
const NodeContextMenu = ({
    isOpen,
    position,
    onClose,
    onEdit,
    onDuplicate,
    onDelete,
    preventDelete,
}: {
    isOpen: boolean;
    position: { x: number; y: number };
    onClose: () => void;
    onEdit: () => void;
    onDuplicate: () => void;
    onDelete: () => void;
    preventDelete: boolean;
}) => {
    const menuRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!isOpen) return;

        const handleClickOutside = (e: globalThis.MouseEvent) => {
            if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
                onClose();
            }
        };

        const handleEscape = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                onClose();
            }
        };

        // Add listeners with a small delay to prevent immediate close
        const timeoutId = setTimeout(() => {
            document.addEventListener('mousedown', handleClickOutside);
            document.addEventListener('keydown', handleEscape);
        }, 10);

        return () => {
            clearTimeout(timeoutId);
            document.removeEventListener('mousedown', handleClickOutside);
            document.removeEventListener('keydown', handleEscape);
        };
    }, [isOpen, onClose]);

    if (!isOpen) return null;

    return createPortal(
        <div
            ref={menuRef}
            className="fixed z-[9999] min-w-[180px] bg-popover text-popover-foreground border rounded-md shadow-lg p-1 animate-in fade-in-0 zoom-in-95"
            style={{
                left: position.x,
                top: position.y,
            }}
        >
            <ContextMenuItem
                onClick={() => { onEdit(); onClose(); }}
                icon={Edit}
                label="Edit"
                shortcut="Double-click"
            />
            <ContextMenuItem
                onClick={() => { onDuplicate(); onClose(); }}
                icon={Copy}
                label="Duplicate"
                shortcut="Ctrl+D"
            />
            <div className="h-px bg-border my-1" />
            <ContextMenuItem
                onClick={() => { onDelete(); onClose(); }}
                icon={Trash2}
                label="Delete"
                shortcut="Del"
                variant="destructive"
                disabled={preventDelete}
            />
        </div>,
        document.body
    );
};

export const NodeContent = ({
    selected,
    invalid,
    selected_through_edge,
    hovered_through_edge,
    title,
    icon,
    nodeType,
    hasSourceHandle = false,
    hasTargetHandle = false,
    children,
    className = "",
    onDoubleClick,
    onEdit,
    nodeId,
    preventDelete = false,
    sourceHandleIds,
}: NodeContentProps) => {
    const badge = getNodeTypeBadge(nodeType);
    const { deleteElements, getNode, addNodes } = useReactFlow();
    const [contextMenuOpen, setContextMenuOpen] = useState(false);
    const [contextMenuPosition, setContextMenuPosition] = useState({ x: 0, y: 0 });

    const handleDelete = useCallback(() => {
        if (nodeId && !preventDelete) {
            deleteElements({ nodes: [{ id: nodeId }] });
        }
    }, [nodeId, preventDelete, deleteElements]);

    const handleDuplicate = useCallback(() => {
        if (!nodeId) return;
        const node = getNode(nodeId);
        if (!node) return;

        const newNode = {
            ...node,
            id: `${node.id}-copy-${Date.now()}`,
            position: {
                x: node.position.x + 50,
                y: node.position.y + 50,
            },
            selected: false,
            data: {
                ...node.data,
                name: `${node.data.name || 'Node'} (Copy)`,
            },
        };
        addNodes(newNode);
    }, [nodeId, getNode, addNodes]);

    const handleEditClick = useCallback(() => {
        if (onEdit) {
            onEdit();
        } else if (onDoubleClick) {
            onDoubleClick();
        }
    }, [onEdit, onDoubleClick]);

    const handleContextMenu = useCallback((e: MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setContextMenuPosition({ x: e.clientX, y: e.clientY });
        setContextMenuOpen(true);
    }, []);

    const closeContextMenu = useCallback(() => {
        setContextMenuOpen(false);
    }, []);

    return (
        <BaseNode
            selected={selected}
            invalid={invalid}
            selected_through_edge={selected_through_edge}
            hovered_through_edge={hovered_through_edge}
            className={`p-0 ${className}`}
            onDoubleClick={onDoubleClick}
            onContextMenu={handleContextMenu}
        >
            {hasTargetHandle && <BaseHandle type="target" position={Position.Top} className="w-3 h-3 border-2 border-background bg-muted-foreground hover:bg-foreground transition-colors" />}

            {/* Header with title and badge */}
            <div className="px-5 pt-5 pb-3">
                <div className="flex items-start justify-between gap-3">
                    <div className="flex flex-col gap-1.5 min-w-0">
                        <div className="flex items-center gap-2">
                            <span className={cn(
                                "flex items-center justify-center w-6 h-6 rounded-md bg-gradient-to-br from-white/5 to-white/10 border border-white/5 text-muted-foreground shadow-sm",
                                selected && "text-foreground from-primary/10 to-teal-500/10 border-primary/20"
                            )}>
                                <span className="[&>*]:w-3.5 [&>*]:h-3.5">{icon}</span>
                            </span>
                            <span className={cn(
                                "inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border uppercase tracking-wider",
                                badge.className
                            )}>
                                {badge.label}
                            </span>
                        </div>
                        <h3 className="text-base font-semibold text-foreground truncate pl-0.5 tracking-tight">
                            {title}
                        </h3>
                    </div>
                </div>
            </div>

            {/* Content area with prompt label */}
            <div className="px-5 pb-5">
                <div className="relative group">
                    <div className="absolute inset-0 bg-gradient-to-br from-white/5 to-transparent rounded-lg -m-2 opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none" />
                    <div className="text-[11px] uppercase tracking-wider text-muted-foreground/70 mb-2 font-semibold">Prompt</div>
                    <div className="text-sm text-muted-foreground/90 leading-relaxed font-light">
                        {children}
                    </div>
                </div>
            </div>

            {hasSourceHandle && !sourceHandleIds && <BaseHandle type="source" position={Position.Bottom} className="w-3 h-3 border-2 border-background bg-muted-foreground hover:bg-foreground transition-colors" />}
            {sourceHandleIds && sourceHandleIds.map((handleId, index) => (
                <BaseHandle
                    key={handleId}
                    type="source"
                    position={Position.Bottom}
                    id={handleId}
                    className="w-3 h-3 border-2 border-background bg-muted-foreground hover:bg-foreground transition-colors"
                    style={{
                        left: `${((index + 1) / (sourceHandleIds.length + 1)) * 100}%`,
                    }}
                />
            ))}

            {/* Context Menu - rendered via portal to document.body */}
            <NodeContextMenu
                isOpen={contextMenuOpen}
                position={contextMenuPosition}
                onClose={closeContextMenu}
                onEdit={handleEditClick}
                onDuplicate={handleDuplicate}
                onDelete={handleDelete}
                preventDelete={preventDelete}
            />
        </BaseNode>
    );
};
