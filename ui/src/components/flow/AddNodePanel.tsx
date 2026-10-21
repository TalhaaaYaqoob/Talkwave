import { Braces, Ear, GitBranch, Globe, Headset, LayoutGrid, ListChecks, OctagonX, PhoneForwarded, Play, X, Zap } from 'lucide-react';
import { useEffect } from 'react';

import { Button } from '@/components/ui/button';

import { NodeType } from './types';

type AddNodePanelProps = {
    isOpen: boolean;
    onClose: () => void;
    onNodeSelect: (nodeType: NodeType) => void;
    callType?: 'INBOUND' | 'OUTBOUND' | 'WEBSITE' | 'MEETING';
};

const NODE_TYPES = [
    {
        type: NodeType.START_CALL,
        label: 'Start Call',
        description: 'Initial greeting when a call begins',
        icon: Play,
    },
    {
        type: NodeType.AGENT_NODE,
        label: 'Agent Node',
        description: 'AI conversation handler with integrations',
        icon: Headset,
    },
    {
        type: NodeType.ACTION_NODE,
        label: 'Action Node',
        description: 'Post-call webhooks & API triggers',
        icon: Zap,
    },
    {
        type: NodeType.CALL_VARIABLES,
        label: 'Call Variables',
        description: 'Post-call data hub for integrations',
        icon: Braces,
    },
    {
        type: NodeType.END_CALL,
        label: 'End Call',
        description: 'End the call gracefully',
        icon: OctagonX,
    }
];

const BRANCHING_NODE_TYPES = [
    {
        type: NodeType.IF_ELSE,
        label: 'If / Else',
        description: 'Binary branch based on a condition',
        icon: GitBranch,
    },
    {
        type: NodeType.CATEGORIZE,
        label: 'Categorize',
        description: 'Multi-way routing by classification',
        icon: LayoutGrid,
    },
    {
        type: NodeType.TRANSFER,
        label: 'Transfer',
        description: 'Hand off to a human or phone number',
        icon: PhoneForwarded,
    },
];

const MEETING_NODE_TYPES = [
    {
        type: NodeType.MEETING_TRIGGER,
        label: 'Meeting Trigger',
        description: 'Respond when wake word is detected in a meeting',
        icon: Ear,
    },
    {
        type: NodeType.MEETING_SUMMARY,
        label: 'Meeting Summary',
        description: 'Generate summary, action items, and notes',
        icon: ListChecks,
    },
];

const GLOBAL_NODE_TYPES = [
    {
        type: NodeType.GLOBAL_NODE,
        label: 'Global Node',
        description: 'Create a global node',
        icon: Globe
    }
]

export default function AddNodePanel({ isOpen, onNodeSelect, onClose, callType }: AddNodePanelProps) {
    const isMeeting = callType === 'MEETING';
    const filteredNodeTypes = isMeeting
        ? NODE_TYPES.filter(n => n.type !== NodeType.START_CALL && n.type !== NodeType.END_CALL)
        : NODE_TYPES;
    useEffect(() => {
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape' && isOpen) {
                onClose();
            }
        };

        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [isOpen, onClose]);

    return (
        <div
            className={`fixed z-51 right-0 top-0 h-full w-80 bg-card/80 backdrop-blur-2xl shadow-2xl border-l border-white/5 transform transition-all duration-300 cubic-bezier(0.4, 0, 0.2, 1) ${
                isOpen ? 'translate-x-0' : 'translate-x-full'
            }`}
        >
            <div className="p-6 h-full overflow-y-auto">
                <div className="flex justify-between items-center mb-8">
                    <h2 className="text-xl font-bold bg-gradient-to-r from-foreground to-foreground/70 bg-clip-text text-transparent">Add Node</h2>
                    <Button
                        variant="ghost"
                        size="icon"
                        onClick={onClose}
                        className="hover:bg-white/10 rounded-full h-8 w-8 text-muted-foreground hover:text-foreground transition-all duration-300"
                    >
                        <X className="w-5 h-5" />
                    </Button>
                </div>

                {isMeeting && (
                <div className="mb-6">
                    <h1 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-4 px-1">Meeting Agent</h1>
                    <div className="space-y-3">
                        {MEETING_NODE_TYPES.map((node) => (
                            <Button
                                key={node.type}
                                variant="ghost"
                                className="w-full justify-start p-3 h-auto group hover:bg-white/5 border border-transparent hover:border-white/10 rounded-xl transition-all duration-300"
                                onClick={() => onNodeSelect(node.type)}
                            >
                                <div className="flex items-center w-full">
                                    <div className="bg-violet-500/10 p-3 rounded-xl mr-4 group-hover:bg-violet-500/20 group-hover:scale-110 transition-all duration-300 border border-violet-500/10">
                                        <node.icon className="h-5 w-5 text-violet-400" />
                                    </div>
                                    <div className="flex flex-col items-start flex-1 min-w-0">
                                        <span className="font-semibold text-foreground/90 group-hover:text-violet-400 transition-colors">{node.label}</span>
                                        <span className="text-xs text-muted-foreground truncate w-full">{node.description}</span>
                                    </div>
                                </div>
                            </Button>
                        ))}
                    </div>
                </div>
                )}

                <div className="mb-6">
                    <h1 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-4 px-1">Agent Nodes</h1>
                    <div className="space-y-3">
                        {filteredNodeTypes.map((node) => (
                            <Button
                                key={node.type}
                                variant="ghost"
                                className="w-full justify-start p-3 h-auto group hover:bg-white/5 border border-transparent hover:border-white/10 rounded-xl transition-all duration-300"
                                onClick={() => onNodeSelect(node.type)}
                            >
                                <div className="flex items-center w-full">
                                    <div className="bg-primary/10 p-3 rounded-xl mr-4 group-hover:bg-primary/20 group-hover:scale-110 transition-all duration-300 border border-primary/10">
                                        <node.icon className="h-5 w-5 text-primary" />
                                    </div>
                                    <div className="flex flex-col items-start flex-1 min-w-0">
                                        <span className="font-semibold text-foreground/90 group-hover:text-primary transition-colors">{node.label}</span>
                                        <span className="text-xs text-muted-foreground truncate w-full">{node.description}</span>
                                    </div>
                                </div>
                            </Button>
                        ))}
                    </div>
                </div>

                {!isMeeting && (
                <div className="mb-6">
                    <h1 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-4 px-1">Branching &amp; Routing</h1>
                    <div className="space-y-3">
                        {BRANCHING_NODE_TYPES.map((node) => (
                            <Button
                                key={node.type}
                                variant="ghost"
                                className="w-full justify-start p-3 h-auto group hover:bg-white/5 border border-transparent hover:border-white/10 rounded-xl transition-all duration-300"
                                onClick={() => onNodeSelect(node.type)}
                            >
                                <div className="flex items-center w-full">
                                    <div className="bg-orange-500/10 p-3 rounded-xl mr-4 group-hover:bg-orange-500/20 group-hover:scale-110 transition-all duration-300 border border-orange-500/10">
                                        <node.icon className="h-5 w-5 text-orange-400" />
                                    </div>
                                    <div className="flex flex-col items-start flex-1 min-w-0">
                                        <span className="font-semibold text-foreground/90 group-hover:text-orange-400 transition-colors">{node.label}</span>
                                        <span className="text-xs text-muted-foreground truncate w-full">{node.description}</span>
                                    </div>
                                </div>
                            </Button>
                        ))}
                    </div>
                </div>
                )}

                <div>
                    <h1 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-4 px-1">Global Nodes</h1>
                    <div className="space-y-3">
                        {GLOBAL_NODE_TYPES.map((node) => (
                            <Button
                                variant="ghost"
                                className="w-full justify-start p-3 h-auto group hover:bg-white/5 border border-transparent hover:border-white/10 rounded-xl transition-all duration-300"
                                key={node.type}
                                onClick={() => onNodeSelect(node.type)}
                            >
                                <div className="flex items-center w-full">
                                    <div className="bg-accent/10 p-3 rounded-xl mr-4 group-hover:bg-accent/20 group-hover:scale-110 transition-all duration-300 border border-accent/10">
                                        <node.icon className="h-5 w-5 text-accent-foreground" />
                                    </div>
                                    <div className="flex flex-col items-start flex-1 min-w-0">
                                        <span className="font-semibold text-foreground/90 group-hover:text-accent-foreground transition-colors">{node.label}</span>
                                        <span className="text-xs text-muted-foreground truncate w-full">{node.description}</span>
                                    </div>
                                </div>
                            </Button>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
}
