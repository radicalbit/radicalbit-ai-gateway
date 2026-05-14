import { numberFormatterInt } from '@Src/constants';
import { faBarsStaggered } from '@fortawesome/free-solid-svg-icons';
import {
  Button, Divider, FontAwesomeIcon, Popover,
} from '@radicalbit/radicalbit-design-system';

function Routing({ routing }) {
  const value = routing?.value;

  if (value === undefined) {
    return (
      <Button disabled shape="circle">
        <FontAwesomeIcon icon={faBarsStaggered} />
      </Button>
    );
  }

  const btnType = value > 0 ? { type: 'primary' } : { type: 'primary-light' };

  return (
    <Popover content={<PopoverContent routing={routing} />} minWidth="250" title={<strong>Total invocations</strong>}>
      <Button shape="circle" {...btnType}>
        <FontAwesomeIcon icon={faBarsStaggered} />
      </Button>
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
