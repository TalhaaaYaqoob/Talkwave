'use client';

import { AlertCircle } from 'lucide-react';
import { forwardRef, ReactNode, useEffect, useRef } from 'react';

import { cn } from '@/lib/utils';

interface InvalidFieldWrapperProps {
    /** The field name to check for validation */
    fieldName: string;
    /** The currently invalid field (from node data) */
    invalidField?: string | null;
    /** The validation message to display */
    validationMessage?: string | null;
    /** Children to wrap */
    children: ReactNode;
    /** Additional class names */
    className?: string;
    /** Whether this is the field that should auto-scroll into view */
    autoScrollOnInvalid?: boolean;
}

/**
 * Wrapper component that highlights a form field when it's invalid.
 * Shows a red border, background tint, and validation message.
 * Optionally scrolls the field into view when invalid.
 */
export const InvalidFieldWrapper = forwardRef<HTMLDivElement, InvalidFieldWrapperProps>(({
    fieldName,
    invalidField,
    validationMessage,
    children,
    className,
    autoScrollOnInvalid = true,
}, ref) => {
    const internalRef = useRef<HTMLDivElement>(null);
    const resolvedRef = (ref as React.RefObject<HTMLDivElement>) || internalRef;
    
    const isInvalid = invalidField === fieldName;

    useEffect(() => {
        if (isInvalid && autoScrollOnInvalid && resolvedRef.current) {
            // Scroll to the invalid field with smooth animation
            resolvedRef.current.scrollIntoView({
                behavior: 'smooth',
                block: 'center',
            });
            
            // Add a brief highlight animation
            resolvedRef.current.animate([
                { transform: 'scale(1)', boxShadow: '0 0 0 0 rgba(239, 68, 68, 0.5)' },
                { transform: 'scale(1.01)', boxShadow: '0 0 0 4px rgba(239, 68, 68, 0.3)' },
                { transform: 'scale(1)', boxShadow: '0 0 0 0 rgba(239, 68, 68, 0)' },
            ], {
                duration: 600,
                easing: 'ease-out',
            });
        }
    }, [isInvalid, autoScrollOnInvalid, resolvedRef]);

    return (
        <div
            ref={resolvedRef}
            className={cn(
                "relative transition-all duration-200",
                isInvalid && "ring-2 ring-red-500/50 rounded-lg p-3 -m-3 bg-red-500/5",
                className
            )}
        >
            {children}
            {isInvalid && validationMessage && (
                <div className="mt-2 flex items-center gap-2 text-sm text-red-500 animate-in fade-in slide-in-from-top-1">
                    <AlertCircle className="h-4 w-4 flex-shrink-0" />
                    <span>{validationMessage}</span>
                </div>
            )}
        </div>
    );
});

InvalidFieldWrapper.displayName = 'InvalidFieldWrapper';

/**
 * Hook to get CSS classes for an input that may be invalid
 */
export function useInvalidFieldClasses(
    fieldName: string,
    invalidField?: string | null
): string {
    const isInvalid = invalidField === fieldName;
    return cn(
        isInvalid && "border-red-500 focus:border-red-500 focus:ring-red-500/20 bg-red-500/5"
    );
}

