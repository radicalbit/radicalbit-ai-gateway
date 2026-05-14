import { Divider, Popover } from '@radicalbit/radicalbit-design-system';

function Errors({ errors }) {
  if (!errors) {
    return '--';
  }

  const { requestErrorPercentage } = errors;

  return (
    <Popover
      content={<PopoverContent errors={errors} />}
      minWidth="250"
      title={<strong>Errors</strong>}
    >
      <span>
        {`${requestErrorPercentage}%`}
      </span>
    </Popover>
  );
}

function PopoverContent({ errors }) {
  const { requestError, requestErrorPercentage, details } = errors;

  return (
    <div className="flex flex-col">
      <PopoverRow label="Total errors:" value={requestError ?? '--'} />

      <PopoverRow label="Error %:" value={requestErrorPercentage !== undefined ? `${requestErrorPercentage}%` : '--'} />

      {details && details.length > 0 && (
        <>
          <Divider style={{ margin: '.5rem' }} />

          <strong>Details</strong>

          <div style={{ maxHeight: 200, overflowY: 'auto' }}>
            {details.map((detail) => (
              <PopoverRow
                key={detail.errorType}
                label={detail.errorType}
                value={detail.count}
              />
            ))}
          </div>
        </>
      )}
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

export default Errors;
