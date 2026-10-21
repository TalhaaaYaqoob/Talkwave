import { forwardRef, HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export const BaseNode = forwardRef<
    HTMLDivElement,
    HTMLAttributes<HTMLDivElement> & {
        selected?: boolean;
        invalid?: boolean;
        selected_through_edge?: boolean;
        hovered_through_edge?: boolean;
    }
>(({ className, selected, invalid, selected_through_edge, hovered_through_edge, ...props }, ref) => (
    <div
        ref={ref}
        className={cn(
            // Base styling - darker glass, premium borders
            "relative rounded-2xl border bg-[#050505]/80 backdrop-blur-xl text-card-foreground min-w-[320px] max-w-[400px] min-h-[120px]",
            // Border styling
            "border-white/5 transition-all duration-300",
            className,
            // Selected state - neon glow
            selected
                ? "border-primary/50 shadow-[0_0_40px_-5px_oklch(var(--primary)/0.2)] ring-1 ring-primary/40 z-10 bg-black/90"
                : "shadow-2xl shadow-black/60 z-0 hover:border-white/10 hover:bg-black/60",
            // Invalid state
            invalid ? "border-destructive/50 shadow-[0_0_20px_rgba(239,68,68,0.2)] bg-destructive/10" : "",
            // Hovered through edge takes precedence - accent glow
            hovered_through_edge ? "ring-1 ring-accent/60 shadow-[0_0_20px_oklch(var(--accent)/0.3)]" : "",
            !hovered_through_edge && selected_through_edge ? "ring-1 ring-accent/50 shadow-[0_0_15px_oklch(var(--accent)/0.2)]" : "",
        )}
        tabIndex={0}
        {...props}
    />
));

BaseNode.displayName = "BaseNode";
