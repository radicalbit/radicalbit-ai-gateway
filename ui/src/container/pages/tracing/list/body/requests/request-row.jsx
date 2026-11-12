import { formatMs, formatTimestamp } from '@Src/helpers/column-formatters';
import formatCost from '@Src/helpers/format-cost';
import {
  NewHeader, Pin, SectionTitle, TextWithBold,
} from '@radicalbit/radicalbit-design-system';
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
    <NewHeader
      details={{ one: <span className="text-xs">{formatTimestamp(createdAt)}</span> }}
      padding="all"
      title={(
        <SectionTitle
          size="small"
          subtitle={(
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              <TextWithBold bold={<CredentialLink apiKeyName={apiKeyName} />} size="small" text="Credential" textProps={LABEL_PROPS} />

              <TextWithBold bold={formatMs(durationMs)} size="small" text="Duration" textProps={LABEL_PROPS} />

              <TextWithBold bold={formatCost(cost)} size="small" text="Cost" textProps={LABEL_PROPS} />
            </div>
          )}
          title={(
            <div className="flex items-center gap-2">
              <strong>{routeName}</strong>

              <RequestTypeCell requestType={requestType} />
            </div>
          )}
          titlePrefix={(
            <span aria-label={label} role="img">
              <Pin size="micro" type={type} />
            </span>
          )}
          titleSuffix={<RequestIcons icons={icons} />}
        />
      )}
    />
  );
}

export default RequestRow;
