import * as React from "react"

import { cn } from "@/lib/utils"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "border-white/5 placeholder:text-muted-foreground/50 focus-visible:border-primary/50 focus-visible:ring-2 focus-visible:ring-primary/20 aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive dark:bg-black/20 hover:bg-white/5 hover:border-white/10 flex field-sizing-content min-h-20 w-full rounded-xl border bg-transparent px-3 py-2 text-base transition-all duration-200 outline-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
