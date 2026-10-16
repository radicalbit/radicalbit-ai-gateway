import { AlertableEventAggregationEnum, AlertScopeEnum, AlertTimeAggregationEnum } from '@Src/constants';
import {
  useGetAlertableEventsQuery, useGetCredentialAlertableEventsQuery, useGetProjectAlertableEventsQuery,
} from '@State/alerts/api';
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
  const credentialUuid = form?.credential;
  const event = form?.event;
  const scope = form?.scope;
  const timeAggregation = form?.timeAggregation;

  const isRouteScope = scope === AlertScopeEnum.ROUTE;
  const isProjectScope = scope === AlertScopeEnum.PROJECT;
  const isCredentialScope = scope === AlertScopeEnum.CREDENTIAL;
  const isDisabled = isCredentialScope
    ? !credentialUuid
    : !projectUuid || (isRouteScope && !routeName);

  const routeEvents = useGetAlertableEventsQuery(
    { projectUuid, routeName },
    { skip: isDisabled || !isRouteScope },
  );

  const projectEvents = useGetProjectAlertableEventsQuery(
    { projectUuid },
    { skip: isDisabled || !isProjectScope },
  );

  const credentialEvents = useGetCredentialAlertableEventsQuery(
    { credentialUuid },
    { skip: isDisabled || !isCredentialScope },
  );

  const eventsByScope = {
    [AlertScopeEnum.PROJECT]: projectEvents,
    [AlertScopeEnum.CREDENTIAL]: credentialEvents,
  };
  const { data, isError, isLoading } = eventsByScope[scope] ?? routeEvents;
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
