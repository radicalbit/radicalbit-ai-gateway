import { DATE_FORMAT } from '@Src/constants';
import { formatMs } from '@Src/helpers/column-formatters';
import formatCost from '@Src/helpers/format-cost';
import {
  NewHeader, Pin, RelativeDateTime, SectionTitle, TextWithBold,
} from '@radicalbit/radicalbit-design-system';
import { RELATIVE_DATE_REFRESH_SECONDS } from './constants';
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
      details={{ one: <span className="text-xs"><RelativeDateTime format={DATE_FORMAT} formatTooltip={DATE_FORMAT} refreshInterval={RELATIVE_DATE_REFRESH_SECONDS} threshold={0} timestamp={createdAt * 1000} withTooltip /></span> }}
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
