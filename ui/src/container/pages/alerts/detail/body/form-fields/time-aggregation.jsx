import {
  ALERT_TIME_AGGREGATION_LABELS,
  ALERT_WINDOW_SIZE_LABELS,
  AlertableEventAggregationEnum,
  AlertTimeAggregationEnum,
  AlertWindowSizeEnum,
} from '@Src/constants';
import { useGetAlertableEventsQuery } from '@State/alerts/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Radio, Select } from '@radicalbit/radicalbit-design-system';
import { useId } from 'react';

const WINDOW_SIZE_OPTIONS = Object.values(AlertWindowSizeEnum).map((value) => ({
  label: ALERT_WINDOW_SIZE_LABELS[value],
  value,
}));

const findAggregation = (alertableEvents, event) => Object.values(alertableEvents ?? {})
  .flat()
  .find((item) => item?.event === event)
  ?.aggregation;

function TimeAggregation() {
  const { form, write } = useFormbitContext();
  const projectUuid = form?.project;
  const routeName = form?.route;
  const event = form?.event;
  const timeAggregation = form?.timeAggregation;

  const { data } = useGetAlertableEventsQuery(
    { projectUuid, routeName },
    { skip: !projectUuid || !routeName },
  );
  const aggregation = findAggregation(data, event);

  const isSelectable = aggregation === AlertableEventAggregationEnum.SELECTABLE;
  const isWindow = timeAggregation === AlertTimeAggregationEnum.WINDOW;

  const handleOnChange = (e) => {
    const value = e?.target?.value;

    write('timeAggregation', value);

    if (value !== AlertTimeAggregationEnum.WINDOW) {
      write('windowSize', undefined);
    }
  };

  if (timeAggregation === AlertTimeAggregationEnum.LIMIT_WINDOW) {
    return <LimitWindow />;
  }

  return (
    <div className="flex flex-col gap-4">
      <FormField label="Notification frequency">
        <Radio.Group
          aria-label="Notification frequency"
          disabled={!isSelectable}
          onChange={handleOnChange}
          value={timeAggregation}
        >
          <Radio value={AlertTimeAggregationEnum.INSTANT}>Instant</Radio>

          <Radio value={AlertTimeAggregationEnum.WINDOW}>Window</Radio>
        </Radio.Group>
      </FormField>

      {isWindow && <WindowSize />}
    </div>
  );
}

function WindowSize() {
  const id = useId();

  const { error, form, write } = useFormbitContext();
  const windowSize = form?.windowSize;

  const handleOnChange = (value) => {
    write('windowSize', value);
  };

  return (
    <FormField htmlFor={id} label="Duration" message={error('windowSize')} required>
      <Select
        id={id}
        onChange={handleOnChange}
        options={WINDOW_SIZE_OPTIONS}
        placeholder="Select a duration"
        value={windowSize}
      />
    </FormField>
  );
}

function LimitWindow() {
  return (
    <FormField label="Notification frequency">
      <div className="flex flex-col gap-2">
        <Radio.Group aria-label="Notification frequency" disabled value={AlertTimeAggregationEnum.LIMIT_WINDOW}>
          <Radio value={AlertTimeAggregationEnum.LIMIT_WINDOW}>
            {ALERT_TIME_AGGREGATION_LABELS[AlertTimeAggregationEnum.LIMIT_WINDOW]}
          </Radio>
        </Radio.Group>

        <span>
          Limit and threshold events follow the window of their limit: the alert is sent the first time
          the event happens in each window, and not again until the limit resets.
        </span>
      </div>
    </FormField>
  );
}

export { findAggregation };

export default TimeAggregation;
