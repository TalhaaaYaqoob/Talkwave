"use client";

import * as React from "react";

/**
 * Unified loader for the whole app.
 *
 * Visual design — the Uiverse "andrew-manzyk" loader: a glowing orb whose
 * surface morphs through a swirl of rotating triangular shapes while the
 * hue cycles. The actual CSS + keyframes live in `globals.css` so the
 * SVG mask animations evaluate correctly without styled-jsx scoping.
 *
 * Two public surfaces:
 *   - <AILoader />              fullscreen, centered, dimmed backdrop.
 *   - <Spinner size="sm|md|lg" /> tiny inline version for buttons / lists.
 *
 * Both render the same underlying ``<UiverseOrb />`` so the design stays
 * unified across pages.
 */

interface OrbProps {
  /** Scale multiplier. 1 = native 100×100 px. */
  scale?: number;
  className?: string;
  /** Wrapper inline styles (e.g. for setting explicit dimensions). */
  style?: React.CSSProperties;
}

/**
 * The Uiverse-by-andrew-manzyk loader, refactored for React.
 *
 * Each instance gets its own SVG ``<mask>`` id so multiple loaders on the
 * same page can't clobber each other.
 */
const UiverseOrb: React.FC<OrbProps> = ({
  scale = 1,
  className = "",
  style,
}) => {
  // Stable per-instance id so the SVG mask never collides with other loaders.
  const reactId = React.useId();
  const maskId = `uiverse-mask-${reactId.replace(/[:]/g, "")}`;

  // Outer wrapper occupies the SCALED footprint (so layout flows correctly).
  // Inner loader stays at the native 100×100 and is visually scaled via
  // a transform on its top-left origin.
  const scaledPx = 100 * scale;

  return (
    <span
      className={className}
      style={{
        ...style,
        display: "inline-block",
        position: "relative",
        width: scaledPx,
        height: scaledPx,
        verticalAlign: "middle",
      }}
      role="status"
      aria-label="Loading"
    >
      <div
        className="uiverse-loader"
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          transformOrigin: "top left",
          transform: `scale(${scale})`,
        }}
      >
        <svg width="100" height="100" viewBox="0 0 100 100" aria-hidden="true">
          <defs>
            <mask id={maskId}>
              <polygon points="0,0 100,0 100,100 0,100" fill="black" />
              <polygon points="25,25 75,25 50,75" fill="white" />
              <polygon points="50,25 75,75 25,75" fill="white" />
              <polygon points="35,35 65,35 50,65" fill="white" />
              <polygon points="35,35 65,35 50,65" fill="white" />
              <polygon points="35,35 65,35 50,65" fill="white" />
              <polygon points="35,35 65,35 50,65" fill="white" />
            </mask>
          </defs>
        </svg>
        <div
          className="uiverse-box"
          style={{
            mask: `url(#${maskId})`,
            WebkitMask: `url(#${maskId})`,
          }}
        />
      </div>
    </span>
  );
};

// ---------------------------------------------------------------------------
// Fullscreen loader
// ---------------------------------------------------------------------------
interface LoaderProps {
  /** Accepted for backwards-compat with existing call sites; never rendered. */
  text?: string;
}

export const AILoader: React.FC<LoaderProps> = () => {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-xl">
      {/* The native loader is 100×100 — scale it up significantly so it reads
       * as the focal point of the screen during agent generation / route loads. */}
      <UiverseOrb scale={2.2} />
    </div>
  );
};

// ---------------------------------------------------------------------------
// Inline spinner (drop-in replacement for the previous lucide Loader2 icon)
// ---------------------------------------------------------------------------
interface SpinnerProps {
  size?: "sm" | "md" | "lg";
  className?: string;
}

const SIZE_SCALE: Record<NonNullable<SpinnerProps["size"]>, number> = {
  sm: 18 / 100, // ~18px — buttons, table rows
  md: 32 / 100, // ~32px — section status
  lg: 56 / 100, // ~56px — large section / dialog content
};

export const Spinner: React.FC<SpinnerProps> = ({
  size = "md",
  className = "",
}) => {
  return (
    <UiverseOrb
      scale={SIZE_SCALE[size]}
      className={className}
      style={{ display: "inline-block", verticalAlign: "middle" }}
    />
  );
};
