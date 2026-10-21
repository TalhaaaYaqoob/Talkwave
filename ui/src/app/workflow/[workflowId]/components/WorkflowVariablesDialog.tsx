'use client';

import { Braces, Copy } from 'lucide-react';
import { useMemo } from 'react';
import { toast } from 'sonner';

import { useWorkflowNodes, useWorkflowStore } from '@/app/workflow/[workflowId]/stores/workflowStore';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';

interface WorkflowVariablesDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
}

type CollectedVar = {
    name: string;
    type?: string;
    description?: string;
    source: string;
    required?: boolean;
};

/**
 * Read-only, workflow-wide view of every variable the agent works with:
 *   - variables extracted from the conversation (per agent/end node)
 *   - variables required to leave a node (exit-condition required_variables)
 *   - pre-call template context variables (campaign / lead seed data)
 *
 * This is the one place a user can see the complete data set available to wire
 * into integration actions as {{variable_name}}. Everything listed here is also
 * available on the End node after the call.
 */
export const WorkflowVariablesDialog = ({ open, onOpenChange }: WorkflowVariablesDialogProps) => {
    const nodes = useWorkflowNodes();
    const templateContextVariables = useWorkflowStore((s) => s.templateContextVariables);

    const { extracted, preCall } = useMemo(() => {
        const extractedMap = new Map<string, CollectedVar>();

        for (const node of nodes) {
            const data = (node.data || {}) as Record<string, unknown>;
            const nodeName = (data.name as string) || node.type || node.id;

            const ev = data.extraction_variables as
                | Array<{ name?: string; type?: string; prompt?: string; required?: boolean }>
                | undefined;
            if (Array.isArray(ev)) {
                for (const v of ev) {
                    const name = (v?.name || '').trim();
                    if (name && !extractedMap.has(name)) {
                        extractedMap.set(name, {
                            name,
                            type: v.type,
                            description: v.prompt,
                            source: nodeName,
                            required: v.required !== false,
                        });
                    }
                }
            }

            const exits = data.exit_conditions as
                | Array<{ required_variables?: Array<{ name?: string; type?: string; description?: string }> }>
                | undefined;
            if (Array.isArray(exits)) {
                for (const ec of exits) {
                    if (Array.isArray(ec?.required_variables)) {
                        for (const rv of ec.required_variables) {
                            const name = (rv?.name || '').trim();
                            if (name && !extractedMap.has(name)) {
                                extractedMap.set(name, {
                                    name,
                                    type: rv.type,
                                    description: rv.description,
                                    source: `${nodeName} (required)`,
                                });
                            }
                        }
                    }
                }
            }
        }

        const preCallList = Object.keys(templateContextVariables || {}).map((k) => ({
            name: k,
            value: templateContextVariables[k],
        }));

        return { extracted: Array.from(extractedMap.values()), preCall: preCallList };
    }, [nodes, templateContextVariables]);

    const copy = (name: string) => {
        navigator.clipboard.writeText(`{{${name}}}`);
        toast.success(`Copied {{${name}}}`);
    };

    const totalCount = extracted.length + preCall.length;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Braces className="w-5 h-5" /> Workflow Variables
                    </DialogTitle>
                    <DialogDescription>
                        Every variable this agent collects, plus pre-call data. Drop any of them into
                        integration actions (API call, webhook, email, sheets, etc.) as{' '}
                        {`{{variable_name}}`}. All of these are available on the End node after the call.
                    </DialogDescription>
                </DialogHeader>

                {totalCount === 0 ? (
                    <div className="text-sm text-muted-foreground py-6 text-center">
                        No variables yet. Enable variable extraction on an agent node (or regenerate the
                        agent with AI) to start collecting data.
                    </div>
                ) : (
                    <div className="space-y-6">
                        {extracted.length > 0 && (
                            <div className="space-y-2">
                                <div className="text-sm font-medium">
                                    Collected during the call ({extracted.length})
                                </div>
                                {extracted.map((v) => (
                                    <div key={v.name} className="flex items-start gap-2 p-2 border rounded-md">
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2">
                                                <code className="text-sm font-medium">{`{{${v.name}}}`}</code>
                                                {v.type && (
                                                    <Badge variant="secondary" className="text-[10px]">
                                                        {v.type}
                                                    </Badge>
                                                )}
                                                {v.required === false && (
                                                    <Badge variant="outline" className="text-[10px]">
                                                        optional
                                                    </Badge>
                                                )}
                                            </div>
                                            {v.description && (
                                                <div className="text-xs text-muted-foreground truncate">
                                                    {v.description}
                                                </div>
                                            )}
                                            <div className="text-[11px] text-muted-foreground mt-0.5">
                                                from: {v.source}
                                            </div>
                                        </div>
                                        <Button size="sm" variant="ghost" onClick={() => copy(v.name)}>
                                            <Copy className="w-4 h-4" />
                                        </Button>
                                    </div>
                                ))}
                            </div>
                        )}

                        {preCall.length > 0 && (
                            <div className="space-y-2">
                                <div className="text-sm font-medium">Pre-call context ({preCall.length})</div>
                                {preCall.map((v) => (
                                    <div key={v.name} className="flex items-start gap-2 p-2 border rounded-md">
                                        <div className="flex-1 min-w-0">
                                            <code className="text-sm font-medium">{`{{${v.name}}}`}</code>
                                            {v.value && (
                                                <div className="text-xs text-muted-foreground truncate">
                                                    default: {v.value}
                                                </div>
                                            )}
                                        </div>
                                        <Button size="sm" variant="ghost" onClick={() => copy(v.name)}>
                                            <Copy className="w-4 h-4" />
                                        </Button>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}
            </DialogContent>
        </Dialog>
    );
};
