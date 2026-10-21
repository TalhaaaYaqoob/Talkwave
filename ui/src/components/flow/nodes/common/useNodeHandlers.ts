import { useCallback, useState } from "react";

import { useWorkflowStore } from "@/app/workflow/[workflowId]/stores/workflowStore";
import { FlowNodeData } from "@/components/flow/types";

interface UseNodeHandlersProps {
    id: string;
    additionalData?: Record<string, string | boolean>;
}

export const useNodeHandlers = ({ id, additionalData = {} }: UseNodeHandlersProps) => {
    const [open, setOpen] = useState(false);
    const updateNode = useWorkflowStore((state) => state.updateNode);
    const deleteNode = useWorkflowStore((state) => state.deleteNode);
    const clearNodeValidation = useWorkflowStore((state) => state.clearNodeValidation);
    const restoreNodeValidation = useWorkflowStore((state) => state.restoreNodeValidation);
    const nodes = useWorkflowStore((state) => state.nodes);

    const handleSaveNodeData = useCallback(
        (updatedData: FlowNodeData) => {
            const currentNode = nodes.find(node => node.id === id);
            if (currentNode) {
                updateNode(id, {
                    data: { ...currentNode.data, ...updatedData, ...additionalData }
                });
            }
        },
        [id, updateNode, additionalData, nodes]
    );

    const handleDeleteNode = useCallback(() => {
        deleteNode(id);
    }, [id, deleteNode]);

    const handleClearValidation = useCallback(() => {
        clearNodeValidation(id);
    }, [id, clearNodeValidation]);

    const handleRestoreValidation = useCallback((message: string, field: string) => {
        restoreNodeValidation(id, message, field);
    }, [id, restoreNodeValidation]);

    return {
        open,
        setOpen,
        handleSaveNodeData,
        handleDeleteNode,
        handleClearValidation,
        handleRestoreValidation,
    };
};
