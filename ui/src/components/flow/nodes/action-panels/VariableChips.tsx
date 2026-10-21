'use client';

import { Variable } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { toast } from 'sonner';

import { Label } from '@/components/ui/label';

type EditableField = HTMLInputElement | HTMLTextAreaElement;

/**
 * Sets the value of a controlled React input/textarea and dispatches a native
 * `input` event so React's synthetic onChange fires. Bypasses React's internal
 * value tracker via the prototype setter, which is the standard technique for
 * programmatically updating controlled components.
 */
function setNativeValue(el: EditableField, value: string) {
    const proto =
        el instanceof HTMLTextAreaElement
            ? HTMLTextAreaElement.prototype
            : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    setter?.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
}

function isEditable(el: Element | null): el is EditableField {
    if (!el) return false;
    const tag = el.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA';
}

interface VariableChipsProps {
    variables: string[];
    label?: string;
    /** Wrap `{{ }}` around the variable name (default true). */
    wrap?: boolean;
    className?: string;
}

/**
 * Renders clickable "available variable" chips. Clicking a chip inserts the
 * variable token at the caret of whichever input/textarea the user last
 * focused. If no field is focused, the token is copied to the clipboard as a
 * fallback.
 */
export function VariableChips({
    variables,
    label = 'Available Variables',
    wrap = true,
    className,
}: VariableChipsProps) {
    // Track the most recently focused editable field so we still have a target
    // even if focus was briefly lost.
    const lastFieldRef = useRef<EditableField | null>(null);

    useEffect(() => {
        const onFocusIn = (e: FocusEvent) => {
            const target = e.target as Element | null;
            if (isEditable(target)) {
                lastFieldRef.current = target;
            }
        };
        document.addEventListener('focusin', onFocusIn);
        return () => document.removeEventListener('focusin', onFocusIn);
    }, []);

    const insert = (variable: string) => {
        const token = wrap ? `{{${variable}}}` : variable;

        const active = document.activeElement;
        let el: EditableField | null = null;
        if (isEditable(active)) {
            el = active;
        } else if (
            lastFieldRef.current &&
            document.contains(lastFieldRef.current)
        ) {
            el = lastFieldRef.current;
        }

        if (!el) {
            navigator.clipboard?.writeText(token).catch(() => { });
            toast.info('Click a field first, then a variable', {
                description: 'Copied to clipboard so you can paste it.',
            });
            return;
        }

        let start: number;
        let end: number;
        try {
            start = el.selectionStart ?? el.value.length;
            end = el.selectionEnd ?? el.value.length;
        } catch {
            // Some input types (number, email) don't support selection.
            start = el.value.length;
            end = el.value.length;
        }

        const newValue = el.value.slice(0, start) + token + el.value.slice(end);
        setNativeValue(el, newValue);

        const caret = start + token.length;
        const target = el;
        requestAnimationFrame(() => {
            target.focus();
            try {
                target.setSelectionRange(caret, caret);
            } catch {
                // selection not supported on this input type — ignore
            }
        });
    };

    if (variables.length === 0) return null;

    return (
        <div className={className ?? 'p-3 rounded-lg bg-muted/30 border border-border/50'}>
            <Label className="text-xs text-muted-foreground flex items-center gap-2 mb-2">
                <Variable className="w-3 h-3" />
                {label}
            </Label>
            <div className="flex flex-wrap gap-1">
                {variables.map((v) => (
                    <code
                        key={v}
                        role="button"
                        tabIndex={-1}
                        title="Click to insert into the focused field"
                        // Prevent the mousedown from stealing focus from the
                        // field the user was editing.
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => insert(v)}
                        className="px-2 py-0.5 text-xs bg-background rounded cursor-pointer hover:bg-primary/10 active:bg-primary/20 transition-colors"
                    >
                        {wrap ? `{{${v}}}` : v}
                    </code>
                ))}
            </div>
        </div>
    );
}
