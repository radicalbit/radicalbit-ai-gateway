import { AlertableEventAggregationEnum, AlertTimeAggregationEnum } from '@Src/constants';
import { useGetAlertableEventsQuery } from '@State/alerts/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Select, Skeleton } from '@radicalbit/radicalbit-design-system';
import { useId } from 'react';
import { findAggregation } from './time-aggregation';

const toOptions = (alertableEvents = {}) => Object.values(alertableEvents)
  .flat()
  .map(({ event, label }) => ({ label, value: event }));

function Event() {
  const id = useId();

  const { error, form, write } = useFormbitContext();
  const projectUuid = form?.project;
  const routeName = form?.route;
  const event = form?.event;
  const timeAggregation = form?.timeAggregation;

  const isDisabled = !projectUuid || !routeName;

  const { data, isError, isLoading } = useGetAlertableEventsQuery(
    { projectUuid, routeName },
    { skip: isDisabled },
  );
  const options = toOptions(data);

  const errorMessage = isError ? 'Unable to load events, please retry later' : undefined;

  const handleOnChange = (value) => {
    const aggregation = findAggregation(data, value);

    write('event', value);

    if (aggregation === AlertableEventAggregationEnum.LIMIT_WINDOW) {
      write('timeAggregation', AlertTimeAggregationEnum.LIMIT_WINDOW);
      write('windowSize', undefined);
      return;
    }

    const isSelectable = aggregation === AlertableEventAggregationEnum.SELECTABLE;

    if (!isSelectable || timeAggregation === AlertTimeAggregationEnum.LIMIT_WINDOW) {
      write('timeAggregation', AlertTimeAggregationEnum.INSTANT);
      write('windowSize', undefined);
    }
  };

  if (isLoading) {
    return <Skeleton.Input active block />;
  }

  return (
    <FormField htmlFor={id} label="Event" message={error('event') || errorMessage} required>
      <Select
        disabled={isDisabled || isError}
        id={id}
        onChange={handleOnChange}
        options={options}
        placeholder="Select an event"
        value={event}
      />
    </FormField>
  );
}

export default Event;
