import HtmlAnchor from '@Components/html-anchor';
import dateFormatter from '@Helpers/date-formatter';
import IconBadge from '@Components/icon-badge';
import Lucide from '@Components/lucide';
import { PathsEnum, SEARCH_PARAMS, numberFormatterInt } from '@Src/constants';
import {
  Divider, Popover,
} from '@radicalbit/radicalbit-design-system';
import { Shield } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

function Guardrails({ guardrails }) {
  const value = guardrails?.value;

  if (value === undefined) {
    return (
      <IconBadge aria-label="Guardrails" disabled>
        <Lucide icon={Shield} />
      </IconBadge>
    );
  }

  const btnType = value > 0 ? { type: 'primary' } : { type: 'primary-light' };

  return (
    <Popover content={<PopoverContent guardrails={guardrails} />} minWidth="250" title={<strong>Guardrails</strong>}>
      <IconBadge aria-label="Guardrails" {...btnType}>
        <Lucide icon={Shield} />
      </IconBadge>
    </Popover>
  );
}

function PopoverContent({ guardrails }) {
  const navigate = useNavigate();
  const { value, lastEvent } = guardrails;
  const count = value != null ? numberFormatterInt(value) : '--';

  const handleOnClick = (e) => {
    e.stopPropagation();
    navigate(`/${PathsEnum.CREDENTIALS}?${SEARCH_PARAMS.credentials}=${encodeURIComponent(lastEvent.apiKeyName)}`);
  };

  if (lastEvent) {
    return (
      <div className="flex flex-col">
        <PopoverRow label="Count:" value={count} />

        <Divider style={{ margin: '.5rem' }} />

        <strong>Last event</strong>

        <PopoverRow label="Name:" value={lastEvent.name} />

        <PopoverRow label="Where:" value={lastEvent.where} />

        <PopoverRow label="Type:" value={lastEvent.type} />

        <PopoverRow label="Behavior:" value={lastEvent.behavior} />

        <PopoverRow label="Credential:" value={<HtmlAnchor onClick={handleOnClick}>{lastEvent.apiKeyName}</HtmlAnchor>} />

        <Divider style={{ margin: '.5rem' }} />

        <div className="flex justify-end">{dateFormatter(lastEvent.timestamp)}</div>
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      <PopoverRow label="Count:" value={count} />

      <Divider style={{ margin: '.5rem' }} />

      <strong>Last event</strong>

      <PopoverRow label="" value="No event yet" />

      <Divider style={{ margin: '.5rem' }} />

      <div className="flex justify-end">--</div>
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

export default Guardrails;
