import IconBadge from '@Components/icon-badge';
import Lucide from '@Components/lucide';
import { numberFormatterFloat, numberFormatterInt } from '@Src/constants';
import {
  Divider, Popover,
} from '@radicalbit/radicalbit-design-system';
import { CircleCheck } from 'lucide-react';

function Caching({ metrics, configuration }) {
  const caching = configuration?.caching;
  const cacheTriggered = metrics?.cache?.cacheTriggered;

  if (caching === undefined) {
    return (
      <IconBadge aria-label="Caching" disabled>
        <Lucide icon={CircleCheck} />
      </IconBadge>
    );
  }

  const btnType = cacheTriggered > 0 ? { type: 'primary' } : { type: 'primary-light' };

  return (
    <Popover content={<PopoverContent configuration={configuration} metrics={metrics} />} minWidth="250" title={<strong>Caching</strong>}>
      <IconBadge aria-label="Caching" {...btnType}>
        <Lucide icon={CircleCheck} />
      </IconBadge>
    </Popover>
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
