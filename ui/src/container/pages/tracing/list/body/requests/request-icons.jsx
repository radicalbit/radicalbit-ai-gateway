import IconBadge from '@Components/icon-badge';
import Lucide from '@Components/lucide';
import { Tooltip } from '@radicalbit/radicalbit-design-system';
import {
  AlignLeft,
  CircleCheck,
  CornerDownRight,
  Shield,
  SlidersHorizontal,
} from 'lucide-react';
import { firedIcons } from './helpers';

export const ICONS = {
  routing: { icon: AlignLeft, label: 'Advanced Routing' },
  guardrail: { icon: Shield, label: 'Guardrails' },
  fallback: { icon: CornerDownRight, label: 'Fallback' },
  limits: { icon: SlidersHorizontal, label: 'Limits' },
  cache: { icon: CircleCheck, label: 'Caching' },
};

const TONE_TYPES = {
  success: 'primary-light',
  warning: 'warning-light',
  error: 'error-light',
};

function RequestIcons({ icons }) {
  const fired = firedIcons(icons);

  return (
    <span className="inline-flex items-center gap-1">
      {fired.map(({ kind, lines, tone }) => (
        <RequestIcon key={kind} kind={kind} lines={lines} tone={tone} />
      ))}
    </span>
  );
}

function RequestIcon({ kind, lines, tone }) {
  const { icon, label } = ICONS[kind];
  const ariaLabel = `${label}: ${lines.join(', ')}`;

  return (
    <Tooltip
      title={(
        <div className="flex flex-col">
          <strong>{label}</strong>

          {lines.map((line, index) => <span key={`${index}-${line}`}>{line}</span>)}
        </div>
      )}
    >
      <IconBadge aria-label={ariaLabel} size="small" type={TONE_TYPES[tone]}>
        <Lucide icon={icon} />
      </IconBadge>
    </Tooltip>
  );
}

export default RequestIcons;
