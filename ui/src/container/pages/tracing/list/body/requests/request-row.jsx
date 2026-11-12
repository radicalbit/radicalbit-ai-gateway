import { formatMs, formatTimestamp } from '@Src/helpers/column-formatters';
import formatCost from '@Src/helpers/format-cost';
import { Pin, TextWithBold } from '@radicalbit/radicalbit-design-system';
import { CredentialLink } from './entity-links';
import RequestIcons from './request-icons';
import RequestTypeCell from './request-type-cell';

const STATUS_PINS = {
  success: { label: 'Status: success', type: 'filled-success' },
  handled_error: { label: 'Status: error', type: 'filled-error' },
  unhandled_error: { label: 'Status: error', type: 'filled-error' },
};

const UNKNOWN_STATUS_PIN = { label: 'Status: unknown', type: 'filled-secondary' };

const LABEL_PROPS = { type: 'secondary' };

function RequestRow({ request }) {
  const apiKeyName = request?.apiKeyName;
  const cost = request?.cost;
  const createdAt = request?.createdAt;
  const durationMs = request?.durationMs;
  const icons = request?.icons;
  const requestStatus = request?.requestStatus;
  const requestType = request?.requestType;
  const routeName = request?.routeName;

  const { label, type } = STATUS_PINS[requestStatus] ?? UNKNOWN_STATUS_PIN;

  return (
    <div className="flex flex-col gap-1 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span aria-label={label} role="img">
          <Pin size="micro" type={type} />
        </span>

        <strong>{routeName}</strong>

        <RequestTypeCell requestType={requestType} />

        <RequestIcons icons={icons} />

        <span className="ml-auto text-xs">{formatTimestamp(createdAt)}</span>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 pl-4 text-xs">
        <TextWithBold bold={<CredentialLink apiKeyName={apiKeyName} />} text="Credential" textProps={LABEL_PROPS} />

        <TextWithBold bold={formatMs(durationMs)} text="Duration" textProps={LABEL_PROPS} />

        <TextWithBold bold={formatCost(cost)} text="Cost" textProps={LABEL_PROPS} />
      </div>
    </div>
  );
}

export default RequestRow;
