import { AlertCircle, ChevronRight } from "lucide-react";
import { ReactNode, useCallback, useEffect, useRef } from "react";

import { FlowNodeData } from "@/components/flow/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

const FIELD_LABELS: Record<string, string> = {
    prompt: "Instructions / Prompt",
    name: "Name",
    tools: "Tools",
    exit_conditions: "Exit Conditions",
    knowledge_base: "Knowledge Base",
    extraction_variables: "Extraction Variables",
    extraction_prompt: "Extraction Prompt",
    actions: "Actions",
    description: "Description",
    "data.prompt": "Instructions / Prompt",
    "data.name": "Name",
};

interface NodeEditDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    nodeData: FlowNodeData;
    title: string;
    children: ReactNode;
    onSave?: () => void;
    hasChanges?: boolean;
    dialogClassName?: string;
    onNavigateToField?: (fieldName: string) => void;
    onClearValidation?: () => void;
}

export const NodeEditDialog = ({
    open,
    onOpenChange,
    nodeData,
    title,
    children,
    onSave,
    hasChanges,
    dialogClassName,
    onNavigateToField,
    onClearValidation,
}: NodeEditDialogProps) => {
    const contentRef = useRef<HTMLDivElement>(null);
    const handleClose = () => onOpenChange(false);

    const handleSave = () => {
        if (onSave) {
            onSave();
        }
    };

    const scrollToField = useCallback((fieldName: string) => {
        if (!contentRef.current) return;

        const normalizedField = fieldName.startsWith("data.") ? fieldName.slice(5) : fieldName;
        const fieldElement = contentRef.current.querySelector(
            `[data-field="${normalizedField}"]`
        ) || contentRef.current.querySelector(
            `[data-field="${fieldName}"]`
        );

        if (fieldElement) {
            fieldElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
            fieldElement.animate([
                { transform: 'scale(1)', boxShadow: '0 0 0 0 rgba(239, 68, 68, 0.5)' },
                { transform: 'scale(1.02)', boxShadow: '0 0 0 8px rgba(239, 68, 68, 0.2)' },
                { transform: 'scale(1)', boxShadow: '0 0 0 0 rgba(239, 68, 68, 0)' },
            ], {
                duration: 800,
                easing: 'ease-out',
            });
        }

        // Also try to focus the first input/textarea inside that field
        if (fieldElement) {
            const focusable = fieldElement.querySelector<HTMLElement>(
                'input, textarea, select, [contenteditable]'
            );
            if (focusable) {
                setTimeout(() => focusable.focus(), 200);
            }
        }
    }, []);

    // Auto-scroll when dialog opens with validation error
    useEffect(() => {
        if (open && nodeData.invalid && nodeData.invalidField) {
            const timer = setTimeout(() => scrollToField(nodeData.invalidField!), 100);
            return () => clearTimeout(timer);
        }
    }, [open, nodeData.invalid, nodeData.invalidField, scrollToField]);

    const handleErrorClick = useCallback(() => {
        if (nodeData.invalidField) {
            const normalizedField = nodeData.invalidField.startsWith("data.")
                ? nodeData.invalidField.slice(5)
                : nodeData.invalidField;
            if (onNavigateToField) {
                onNavigateToField(normalizedField);
            }
            setTimeout(() => scrollToField(nodeData.invalidField!), 150);
        }
    }, [nodeData.invalidField, onNavigateToField, scrollToField]);

    const fieldLabel = nodeData.invalidField
        ? FIELD_LABELS[nodeData.invalidField] || nodeData.invalidField
        : null;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent
                className={cn("max-h-[85vh] flex flex-col overflow-hidden", dialogClassName)}
                style={{ maxWidth: "1200px", width: "95vw" }}
            >
                <DialogHeader className="flex-shrink-0">
                    <DialogTitle>{title}</DialogTitle>
                    <DialogDescription>
                        Configure the settings for this node in your workflow.
                    </DialogDescription>
                    {nodeData.invalid && nodeData.validationMessage && (
                        <button
                            type="button"
                            onClick={handleErrorClick}
                            className={cn(
                                "mt-2 w-full flex items-center gap-2 rounded-md p-3 text-sm text-left transition-all",
                                "bg-red-500/10 text-red-500 border border-red-500/20",
                                "hover:bg-red-500/15 hover:border-red-500/30",
                                nodeData.invalidField && "cursor-pointer"
                            )}
                        >
                            <AlertCircle className="h-4 w-4 flex-shrink-0" />
                            <div className="flex-1 min-w-0">
                                <p className="font-medium">{nodeData.validationMessage}</p>
                                {fieldLabel && (
                                    <p className="text-xs text-red-400 mt-0.5 flex items-center gap-1">
                                        Click to go to: <span className="font-medium">{fieldLabel}</span>
                                        <ChevronRight className="h-3 w-3" />
                                    </p>
                                )}
                            </div>
                        </button>
                    )}
                </DialogHeader>
                <div ref={contentRef} className="grid gap-4 py-4 flex-1 overflow-y-auto min-h-0">
                    {children}
                </div>
                <DialogFooter className="flex-shrink-0 border-t pt-4">
                    <div className="flex items-center gap-2">
                        <Button variant="outline" onClick={handleClose}>Cancel</Button>
                        <Button onClick={handleSave} disabled={hasChanges === false}>Save</Button>
                    </div>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};
