import IconBadge from '@Components/icon-badge';
import Lucide from '@Components/lucide';
import {
  AlignLeft,
  CircleCheck,
  CornerDownRight,
  Shield,
  SlidersHorizontal,
} from 'lucide-react';

/**
 * The kinds of event that have an icon, with the icon the Routes page uses for each.
 * @type {Record<string, { label: string, icon: import('lucide-react').LucideIcon }>}
 */
export const EVENT_ICONS = {
  guardrail: { label: 'Guardrail', icon: Shield },
  cache: { label: 'Cache', icon: CircleCheck },
  fallback: { label: 'Fallback', icon: CornerDownRight },
  routing: { label: 'Advanced routing', icon: AlignLeft },
  limits: { label: 'Limits', icon: SlidersHorizontal },
};

/**
 * @typedef {object} EventIconProps
 * @property {keyof typeof EVENT_ICONS} kind
 * @property {boolean} fired True when an event of this kind was recorded
 * @property {'small' | 'middle' | 'large'} [size]
 */

/**
 * One event icon: lit (primary) when an event of its kind fired, unlit (disabled) otherwise.
 * @param {EventIconProps} props
 */
function EventIcon({ kind, fired, size }) {
  const { label, icon } = EVENT_ICONS[kind];

  if (fired) {
    return (
      <IconBadge aria-label={`${label}: fired`} size={size} type="primary">
        <Lucide icon={icon} />
      </IconBadge>
    );
  }

  return (
    <IconBadge aria-label={`${label}: no event`} disabled size={size}>
      <Lucide icon={icon} />
    </IconBadge>
  );
}

export default EventIcon;
