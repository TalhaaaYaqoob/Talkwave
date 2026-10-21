'use client';

import {
    ChevronDown,
    ChevronUp,
    GitFork,
    Plus,
    Trash2,
    Variable
} from 'lucide-react';
import { useState } from 'react';

import { ExitCondition, ExitConditionVariable } from '@/components/flow/types';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';

interface ExitConditionsPanelProps {
    exitConditions: ExitCondition[];
    setExitConditions: (conditions: ExitCondition[]) => void;
}

export function ExitConditionsPanel({
    exitConditions,
    setExitConditions
}: ExitConditionsPanelProps) {
    const [expandedConditions, setExpandedConditions] = useState<Set<string>>(new Set());
    const [showNewForm, setShowNewForm] = useState(false);

    // New exit condition form state
    const [newCondition, setNewCondition] = useState<Omit<ExitCondition, 'id'>>({
        name: '',
        llm_description: '',
        required_variables: [],
    });

    const toggleExpand = (conditionId: string) => {
        const newExpanded = new Set(expandedConditions);
        if (newExpanded.has(conditionId)) {
            newExpanded.delete(conditionId);
        } else {
            newExpanded.add(conditionId);
        }
        setExpandedConditions(newExpanded);
    };

    const handleAddCondition = () => {
        if (!newCondition.name || !newCondition.llm_description) {
            return;
        }
        const condition: ExitCondition = {
            id: `exit-${Date.now()}`,
            ...newCondition,
        };
        setExitConditions([...exitConditions, condition]);
        setShowNewForm(false);
        setNewCondition({
            name: '',
            llm_description: '',
            required_variables: [],
        });
    };

    const handleRemoveCondition = (conditionId: string) => {
        setExitConditions(exitConditions.filter(c => c.id !== conditionId));
    };

    const handleUpdateCondition = (conditionId: string, updates: Partial<ExitCondition>) => {
        setExitConditions(exitConditions.map(c =>
            c.id === conditionId ? { ...c, ...updates } : c
        ));
    };

    const handleAddVariable = (conditionId: string) => {
        const condition = exitConditions.find(c => c.id === conditionId);
        if (!condition) return;

        const newVar: ExitConditionVariable = {
            name: '',
            type: 'string',
            description: '',
        };
        handleUpdateCondition(conditionId, {
            required_variables: [...(condition.required_variables ?? []), newVar],
        });
    };

    const handleUpdateVariable = (
        conditionId: string,
        varIdx: number,
        updates: Partial<ExitConditionVariable>
    ) => {
        const condition = exitConditions.find(c => c.id === conditionId);
        if (!condition) return;

        const newVars = [...(condition.required_variables ?? [])];
        newVars[varIdx] = { ...newVars[varIdx], ...updates };
        handleUpdateCondition(conditionId, { required_variables: newVars });
    };

    const handleRemoveVariable = (conditionId: string, varIdx: number) => {
        const condition = exitConditions.find(c => c.id === conditionId);
        if (!condition) return;

        const newVars = (condition.required_variables ?? []).filter((_, i) => i !== varIdx);
        handleUpdateCondition(conditionId, { required_variables: newVars });
    };

    const handleAddNewFormVariable = () => {
        setNewCondition({
            ...newCondition,
            required_variables: [
                ...newCondition.required_variables,
                { name: '', type: 'string', description: '' },
            ],
        });
    };

    const handleUpdateNewFormVariable = (varIdx: number, updates: Partial<ExitConditionVariable>) => {
        const newVars = [...newCondition.required_variables];
        newVars[varIdx] = { ...newVars[varIdx], ...updates };
        setNewCondition({ ...newCondition, required_variables: newVars });
    };

    const handleRemoveNewFormVariable = (varIdx: number) => {
        setNewCondition({
            ...newCondition,
            required_variables: newCondition.required_variables.filter((_, i) => i !== varIdx),
        });
    };

    return (
        <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-2">
            <div className="space-y-2">
                <Label className="text-base font-semibold">Exit Conditions</Label>
                <p className="text-sm text-muted-foreground">
                    Define paths that the agent can take based on conversation intent. When an exit condition
                    is triggered, the conversation will follow the connected edge to the next node.
                </p>
            </div>

            {/* Current exit conditions list */}
            {exitConditions.length > 0 ? (
                <div className="space-y-2">
                    {exitConditions.map((condition) => {
                        const isExpanded = expandedConditions.has(condition.id);

                        return (
                            <div
                                key={condition.id}
                                className="border rounded-lg bg-muted/20"
                            >
                                <div className="p-3">
                                    <div className="flex items-start justify-between">
                                        <div className="flex items-start gap-3">
                                            <div className="p-2 rounded-md bg-amber-500/10 text-amber-600">
                                                <GitFork className="w-4 h-4" />
                                            </div>
                                            <div className="space-y-1">
                                                <div className="flex items-center gap-2">
                                                    <span className="font-medium">{condition.name}</span>
                                                    {(condition.required_variables?.length ?? 0) > 0 && (
                                                        <Badge variant="outline" className="text-xs">
                                                            {condition.required_variables?.length} vars
                                                        </Badge>
                                                    )}
                                                </div>
                                                <p className="text-sm text-muted-foreground line-clamp-2">
                                                    {condition.llm_description}
                                                </p>
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-1">
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                onClick={() => toggleExpand(condition.id)}
                                            >
                                                {isExpanded ? (
                                                    <ChevronUp className="w-4 h-4" />
                                                ) : (
                                                    <ChevronDown className="w-4 h-4" />
                                                )}
                                            </Button>
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                onClick={() => handleRemoveCondition(condition.id)}
                                            >
                                                <Trash2 className="w-4 h-4 text-muted-foreground" />
                                            </Button>
                                        </div>
                                    </div>
                                </div>

                                {isExpanded && (
                                    <div className="px-3 pb-3 pt-0 border-t space-y-3">
                                        <div className="space-y-2 pt-3">
                                            <Label className="text-sm">
                                                Name <span className="text-red-500">*</span>
                                            </Label>
                                            <Input
                                                value={condition.name}
                                                onChange={(e) => handleUpdateCondition(condition.id, { name: e.target.value })}
                                                placeholder="e.g., Process Return Request"
                                            />
                                        </div>

                                        <div className="space-y-2">
                                            <Label className="text-sm">
                                                LLM Description <span className="text-red-500">*</span>
                                            </Label>
                                            <Textarea
                                                value={condition.llm_description}
                                                onChange={(e) => handleUpdateCondition(condition.id, { llm_description: e.target.value })}
                                                placeholder="Trigger this path when the user wants to return an item..."
                                                className="min-h-[80px]"
                                            />
                                        </div>

                                        <div className="space-y-2">
                                            <div className="flex items-center justify-between">
                                                <Label className="text-sm flex items-center gap-1">
                                                    <Variable className="w-4 h-4" />
                                                    Required Variables
                                                </Label>
                                                <Button
                                                    variant="outline"
                                                    size="sm"
                                                    onClick={() => handleAddVariable(condition.id)}
                                                >
                                                    <Plus className="w-3 h-3 mr-1" />
                                                    Add
                                                </Button>
                                            </div>
                                            <p className="text-xs text-muted-foreground">
                                                Variables that must be collected before this exit can trigger.
                                            </p>

                                            {(condition.required_variables?.length ?? 0) > 0 ? (
                                                <div className="space-y-2">
                                                    {(condition.required_variables ?? []).map((v, idx) => (
                                                        <div key={idx} className="flex items-start gap-2 p-2 border rounded bg-background">
                                                            <Input
                                                                placeholder="Variable name"
                                                                value={v.name}
                                                                onChange={(e) => handleUpdateVariable(condition.id, idx, { name: e.target.value })}
                                                                className="flex-1"
                                                            />
                                                            <select
                                                                className="border rounded-md p-2 text-sm bg-background h-9"
                                                                value={v.type}
                                                                onChange={(e) => handleUpdateVariable(condition.id, idx, {
                                                                    type: e.target.value as 'string' | 'number' | 'boolean'
                                                                })}
                                                            >
                                                                <option value="string">String</option>
                                                                <option value="number">Number</option>
                                                                <option value="boolean">Boolean</option>
                                                            </select>
                                                            <Button
                                                                variant="ghost"
                                                                size="icon"
                                                                onClick={() => handleRemoveVariable(condition.id, idx)}
                                                            >
                                                                <Trash2 className="w-4 h-4 text-muted-foreground" />
                                                            </Button>
                                                        </div>
                                                    ))}
                                                </div>
                                            ) : (
                                                <p className="text-xs text-muted-foreground italic">
                                                    No required variables. The exit can trigger without collecting data first.
                                                </p>
                                            )}
                                        </div>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            ) : (
                <div className="border border-dashed rounded-lg p-6 text-center">
                    <GitFork className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
                    <p className="text-sm text-muted-foreground">
                        No exit conditions defined. Add exit conditions to create conversation branches.
                    </p>
                </div>
            )}

            {/* Add new exit condition */}
            {!showNewForm ? (
                <Button
                    variant="outline"
                    className="w-full"
                    onClick={() => setShowNewForm(true)}
                >
                    <Plus className="w-4 h-4 mr-2" />
                    Add Exit Condition
                </Button>
            ) : (
                <div className="border rounded-lg p-4 space-y-4 bg-muted/10">
                    <Label className="font-medium">New Exit Condition</Label>

                    <div className="space-y-2">
                        <Label className="text-sm">
                            Name <span className="text-red-500">*</span>
                        </Label>
                        <Input
                            value={newCondition.name}
                            onChange={(e) => setNewCondition({ ...newCondition, name: e.target.value })}
                            placeholder="e.g., Process Order Return"
                        />
                    </div>

                    <div className="space-y-2">
                        <Label className="text-sm">
                            LLM Description <span className="text-red-500">*</span>
                        </Label>
                        <Textarea
                            value={newCondition.llm_description}
                            onChange={(e) => setNewCondition({ ...newCondition, llm_description: e.target.value })}
                            placeholder="Trigger this path when the user wants to return an item they purchased, expresses dissatisfaction with their order, or asks about the return policy..."
                            className="min-h-[100px]"
                        />
                        <p className="text-xs text-muted-foreground">
                            Describe when this exit should be triggered. Be specific about user intent and phrases.
                        </p>
                    </div>

                    <div className="space-y-2">
                        <div className="flex items-center justify-between">
                            <Label className="text-sm">Required Variables (Optional)</Label>
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={handleAddNewFormVariable}
                            >
                                <Plus className="w-3 h-3 mr-1" />
                                Add Variable
                            </Button>
                        </div>

                        {newCondition.required_variables.length > 0 && (
                            <div className="space-y-2">
                                {newCondition.required_variables.map((v, idx) => (
                                    <div key={idx} className="space-y-2 p-2 border rounded bg-background">
                                        <div className="flex items-center gap-2">
                                            <Input
                                                placeholder="Variable name"
                                                value={v.name}
                                                onChange={(e) => handleUpdateNewFormVariable(idx, { name: e.target.value })}
                                                className="flex-1"
                                            />
                                            <select
                                                className="border rounded-md p-2 text-sm bg-background h-9"
                                                value={v.type}
                                                onChange={(e) => handleUpdateNewFormVariable(idx, {
                                                    type: e.target.value as 'string' | 'number' | 'boolean'
                                                })}
                                            >
                                                <option value="string">String</option>
                                                <option value="number">Number</option>
                                                <option value="boolean">Boolean</option>
                                            </select>
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                onClick={() => handleRemoveNewFormVariable(idx)}
                                            >
                                                <Trash2 className="w-4 h-4 text-muted-foreground" />
                                            </Button>
                                        </div>
                                        <Input
                                            placeholder="Description of this variable"
                                            value={v.description}
                                            onChange={(e) => handleUpdateNewFormVariable(idx, { description: e.target.value })}
                                        />
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    <div className="flex justify-end gap-2">
                        <Button
                            variant="ghost"
                            onClick={() => {
                                setShowNewForm(false);
                                setNewCondition({
                                    name: '',
                                    llm_description: '',
                                    required_variables: [],
                                });
                            }}
                        >
                            Cancel
                        </Button>
                        <Button
                            onClick={handleAddCondition}
                            disabled={!newCondition.name || !newCondition.llm_description}
                        >
                            Add Exit Condition
                        </Button>
                    </div>
                </div>
            )}
        </div>
    );
}

