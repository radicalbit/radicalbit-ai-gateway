import IconBadge from '@Components/icon-badge';
import Lucide from '@Components/lucide';
import InfoPopover from '@Components/info-popover';
import { numberFormatterFloat, numberFormatterInt } from '@Src/constants';
import { Divider } from '@radicalbit/radicalbit-design-system';
import { CircleCheck } from 'lucide-react';

function Caching({ metrics, configuration }) {
  const caching = configuration?.caching;
  const cacheTriggered = metrics?.cache?.cacheTriggered;

  if (caching === undefined) {
    return (
      <IconBadge aria-label="Caching: not configured" disabled>
        <Lucide icon={CircleCheck} />
      </IconBadge>
    );
  }

  const isTriggered = cacheTriggered > 0;
  const btnType = isTriggered ? { type: 'primary' } : { type: 'primary-light' };
  const ariaLabel = isTriggered ? 'Caching: triggered' : 'Caching: not triggered';

  return (
    <InfoPopover content={<PopoverContent configuration={configuration} metrics={metrics} />} minWidth="250" title={<strong>Caching</strong>}>
      <IconBadge aria-label={ariaLabel} {...btnType}>
        <Lucide icon={CircleCheck} />
      </IconBadge>
    </InfoPopover>
  );
}

function PopoverContent({ configuration, metrics }) {
  const type = configuration?.caching?.type;
  const hitPercentage = metrics?.cache?.hitPercentage ? `${numberFormatterFloat(metrics?.cache?.hitPercentage)}%` : '--';
  const count = numberFormatterInt(metrics?.cache?.cacheTriggered) ?? '--';

  if (type) {
    return (
      <div className="flex flex-col">
        <PopoverRow label="Count:" value={count} />

        <Divider style={{ margin: '.5rem' }} />

        <PopoverRow label="Type:" value={type} />

        <PopoverRow label="Hit %:" value={hitPercentage} />
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      <PopoverRow label="Count:" value={count} />

      <Divider style={{ margin: '.5rem' }} />

      <PopoverRow label="Type:" value="--" />

      <PopoverRow label="Hit %:" value="--" />
    </div>
  );
}

function PopoverRow({ label, value }) {
  return (
    <div className="flex justify-between gap-2">
      <div>{label}</div>

      <div>{value}</div>
    </div>
  );
}

export default Caching;
