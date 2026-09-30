import IconBadge from '@Components/icon-badge';
import Lucide from '@Components/lucide';
import { numberFormatterInt } from '@Src/constants';
import {
  Divider, Popover,
} from '@radicalbit/radicalbit-design-system';
import { AlignLeft } from 'lucide-react';

function Routing({ routing }) {
  const value = routing?.value;

  if (value === undefined) {
    return (
      <IconBadge aria-label="Advanced Routing" disabled>
        <Lucide icon={AlignLeft} />
      </IconBadge>
    );
  }

  const btnType = value > 0 ? { type: 'primary' } : { type: 'primary-light' };

  return (
    <Popover content={<PopoverContent routing={routing} />} minWidth="250" title={<strong>Total invocations</strong>}>
      <IconBadge aria-label="Advanced Routing" {...btnType}>
        <Lucide icon={AlignLeft} />
      </IconBadge>
    </Popover>
  );
}

function PopoverContent({ routing }) {
  const { value, modelInvocations = [] } = routing;
  const count = value != null ? numberFormatterInt(value) : '--';

  if (modelInvocations.length === 0) {
    return (
      <div className="flex flex-col">
        <PopoverRow label="Count:" value={count} />

        <Divider style={{ margin: '.5rem' }} />

        <strong>Model invocations</strong>

        <div>--</div>
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      <PopoverRow label="Count:" value={count} />

      <Divider style={{ margin: '.5rem' }} />

      <strong>Model invocations</strong>

      {modelInvocations.map((inv) => (
        <PopoverRow key={inv.modelId} label={inv.modelId} value={numberFormatterInt(inv.value)} />
      ))}
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

export default Routing;
