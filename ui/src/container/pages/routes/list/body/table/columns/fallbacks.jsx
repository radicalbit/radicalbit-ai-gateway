import HtmlAnchor from '@Components/html-anchor';
import dateFormatter from '@Helpers/date-formatter';
import Lucide from '@Components/lucide';
import { PathsEnum, SEARCH_PARAMS, numberFormatterInt } from '@Src/constants';
import {
  Button, Divider, Popover,
} from '@radicalbit/radicalbit-design-system';
import { CornerDownRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

function Fallbacks({ fallbacks }) {
  const value = fallbacks?.value;

  if (value === undefined) {
    return (
      <Button disabled shape="circle">
        <Lucide icon={CornerDownRight} />
      </Button>
    );
  }

  const btnType = value > 0 ? { type: 'primary' } : { type: 'primary-light' };

  return (
    <Popover content={<PopoverContent fallbacks={fallbacks} />} minWidth="250" title={<strong>Fallback</strong>}>
      <Button shape="circle" {...btnType}>
        <Lucide icon={CornerDownRight} />
      </Button>
    </Popover>
  );
}

function PopoverContent({ fallbacks }) {
  const navigate = useNavigate();
  const { value, lastEvent } = fallbacks;
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

        <PopoverRow label="Target:" value={lastEvent.target} />

        <PopoverRow label="Fallback:" value={lastEvent.fallback} />

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

export default Fallbacks;
