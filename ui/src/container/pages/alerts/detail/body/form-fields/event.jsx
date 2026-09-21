import { useGetAlertableEventsQuery } from '@State/alerts/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Select, Skeleton } from '@radicalbit/radicalbit-design-system';

const toOptions = (alertableEvents = {}) => Object.values(alertableEvents)
  .flat()
  .map(({ event, label }) => ({ label, value: event }));

function Event() {
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

  const eventsErrorMessage = isError ? 'Unable to load events, please retry later' : undefined;

  const handleOnChange = (value) => {
    write('event', value);
  };

  if (isLoading) {
    return <Skeleton.Input active block />;
  }

  return (
    <FormField label="Event" message={error('event') || eventsErrorMessage} required>
      <Select
        disabled={isDisabled || isError}
        onChange={handleOnChange}
        options={options}
        placeholder="Select an event"
        value={event}
      />
    </FormField>
  );
}

export default Event;
