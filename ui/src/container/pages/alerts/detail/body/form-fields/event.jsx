import { AlertableEventAggregationEnum, AlertTimeAggregationEnum } from '@Src/constants';
import { useGetAlertableEventsQuery } from '@State/alerts/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Select, Skeleton } from '@radicalbit/radicalbit-design-system';
import { useId } from 'react';

const toOptions = (alertableEvents = {}) => Object.values(alertableEvents)
  .flat()
  .map(({ event, label }) => ({ label, value: event }));

const toTimeAggregation = (alertableEvents, event) => {
  const aggregation = Object.values(alertableEvents ?? {})
    .flat()
    .find((item) => item?.event === event)
    ?.aggregation;

  return aggregation === AlertableEventAggregationEnum.LIMIT_WINDOW
    ? AlertTimeAggregationEnum.LIMIT_WINDOW
    : AlertTimeAggregationEnum.INSTANT;
};

function Event() {
  const id = useId();

  const { error, form, write } = useFormbitContext();
  const projectUuid = form?.project;
  const routeName = form?.route;
  const event = form?.event;

  const isDisabled = !projectUuid || !routeName;

  const { data, isError, isLoading } = useGetAlertableEventsQuery(
    { projectUuid, routeName },
    { skip: isDisabled },
  );
  const options = toOptions(data);

  const errorMessage = isError ? 'Unable to load events, please retry later' : undefined;

  const handleOnChange = (value) => {
    write('event', value);
    write('timeAggregation', toTimeAggregation(data, value));
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
