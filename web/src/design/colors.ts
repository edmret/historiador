/**
 * Historiador color tokens.
 *
 * All values are declared as CSS custom property names so consuming code is
 * decoupled from the literal palette. The CSS variables themselves are defined
 * in src/styles/base.css inside an @theme block (Tailwind v4 convention).
 *
 * Dark is the designed state, not an inversion (ARCHITECTURE.md §9).
 * Every surface name is a semantic alias — never a hue description.
 */

// ─── Semantic surface scale ────────────────────────────────────────────────

/** Deepest background — page floor. */
export const COLOR_SURFACE_VOID = 'var(--color-surface-void)' as const

/** Primary application background. */
export const COLOR_SURFACE_BASE = 'var(--color-surface-base)' as const

/** Elevated panel / sidebar background. */
export const COLOR_SURFACE_RAISED = 'var(--color-surface-raised)' as const

/** Card / inset content area. */
export const COLOR_SURFACE_OVERLAY = 'var(--color-surface-overlay)' as const

/** Highest elevation — modal, command palette. */
export const COLOR_SURFACE_FLOAT = 'var(--color-surface-float)' as const

// ─── Borders & separators ─────────────────────────────────────────────────

/** Hairline separator — muted, almost invisible. */
export const COLOR_BORDER_SUBTLE = 'var(--color-border-subtle)' as const

/** Standard border for panels and inputs. */
export const COLOR_BORDER_DEFAULT = 'var(--color-border-default)' as const

/** Prominent border / focus ring container. */
export const COLOR_BORDER_STRONG = 'var(--color-border-strong)' as const

// ─── Text ─────────────────────────────────────────────────────────────────

/** Primary body copy. */
export const COLOR_TEXT_PRIMARY = 'var(--color-text-primary)' as const

/** Labels, secondary information. */
export const COLOR_TEXT_SECONDARY = 'var(--color-text-secondary)' as const

/** Placeholder, disabled, decorative. */
export const COLOR_TEXT_MUTED = 'var(--color-text-muted)' as const

/** Text on interactive / accent backgrounds. */
export const COLOR_TEXT_ON_ACCENT = 'var(--color-text-on-accent)' as const

// ─── Brand / accent ──────────────────────────────────────────────────────

/** Primary interaction color — links, active nav, primary buttons. */
export const COLOR_ACCENT_PRIMARY = 'var(--color-accent-primary)' as const

/** Hover / pressed variant of the primary accent. */
export const COLOR_ACCENT_PRIMARY_HOVER =
  'var(--color-accent-primary-hover)' as const

/** Subtle tint for accent backgrounds (badges, highlights). */
export const COLOR_ACCENT_PRIMARY_SUBTLE =
  'var(--color-accent-primary-subtle)' as const

// ─── Node / run state palette ────────────────────────────────────────────

/** Running / in-progress. */
export const COLOR_STATE_RUNNING = 'var(--color-state-running)' as const
export const COLOR_STATE_RUNNING_SUBTLE =
  'var(--color-state-running-subtle)' as const

/** Blocked / waiting for deps. */
export const COLOR_STATE_BLOCKED = 'var(--color-state-blocked)' as const

/** Succeeded / complete. */
export const COLOR_STATE_SUCCESS = 'var(--color-state-success)' as const
export const COLOR_STATE_SUCCESS_SUBTLE =
  'var(--color-state-success-subtle)' as const

/** Failed / errored. */
export const COLOR_STATE_ERROR = 'var(--color-state-error)' as const
export const COLOR_STATE_ERROR_SUBTLE =
  'var(--color-state-error-subtle)' as const

/** Retrying. */
export const COLOR_STATE_RETRYING = 'var(--color-state-retrying)' as const
export const COLOR_STATE_RETRYING_SUBTLE =
  'var(--color-state-retrying-subtle)' as const

/** Skipped / cancelled. */
export const COLOR_STATE_SKIPPED = 'var(--color-state-skipped)' as const

// ─── Convenience map (for programmatic lookup by state key) ──────────────

export const NODE_STATE_COLORS = {
  BLOCKED: COLOR_STATE_BLOCKED,
  READY: COLOR_STATE_RUNNING_SUBTLE,
  RUNNING: COLOR_STATE_RUNNING,
  RETRYING: COLOR_STATE_RETRYING,
  SUCCEEDED: COLOR_STATE_SUCCESS,
  FAILED: COLOR_STATE_ERROR,
  CANCELLED: COLOR_STATE_SKIPPED,
  SKIPPED: COLOR_STATE_SKIPPED,
} as const

export type NodeStateColorKey = keyof typeof NODE_STATE_COLORS
