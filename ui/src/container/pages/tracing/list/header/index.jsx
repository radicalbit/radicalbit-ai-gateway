import Lucide from '@Components/lucide';
import TagsFilter from '@Components/tags-filter';
import { TimeFilterCustomOnly } from '@Components/time-filter';
import { FormField, NewHeader, SectionTitle, Select } from '@radicalbit/radicalbit-design-system';
import { REQUEST_TYPE_LABELS, RequestTypeEnum } from '@Src/constants';
import { useGetRoutesWithRange } from '@Src/store/state/routes/vertical-hooks';
import { Route } from 'lucide-react';
import { useId } from 'react';
import { useSearchParams } from 'react-router-dom';
import ProjectFilter from './project-filter';

const keys = ['routes', 'requestType', 'preset', 'from', 'to'];
const storageKey = 'rbit-gw-tracing';

const REQUEST_TYPE_OPTIONS = Object.values(RequestTypeEnum)
  .map((value) => ({ label: REQUEST_TYPE_LABELS[value], value }));

function TracingListHeader() {
  const projectId = useId();
  const tagsId = useId();
  const routesId = useId();
  const requestTypeId = useId();

  const [searchParams] = useSearchParams();
  const isTracingTab = searchParams.get('tab') === 'tracing';

  const requestTypeFilter = isTracingTab ? (
    <FormField htmlFor={requestTypeId} label="Type">
      <RequestTypeSelector id={requestTypeId} />
    </FormField>
  ) : false;

  return (
    <NewHeader
      details={{
        one: (
          <div className="flex flex-row items-center gap-4">
            <FormField htmlFor={projectId} label="Project">
              <ProjectFilter id={projectId} />
            </FormField>

            <FormField htmlFor={tagsId} label="Tags">
              <TagsFilter id={tagsId} />
            </FormField>

            {requestTypeFilter}

            <FormField htmlFor={routesId} label="Routes">
              <RouteSelector id={routesId} />
            </FormField>
          </div>
        ),
        two: (
          <div className="flex items-end h-full">
            <TimeFilterCustomOnly keys={keys} storageKey={storageKey} />
          </div>),
      }}
      title={(
        <SectionTitle
          subtitle="Inspect individual requests processed by the gateway."
          title="Tracing"
          titlePrefix={<Lucide icon={Route} />}
        />
      )}
    />
  );
}

function RouteSelector({ id }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const { data = [], isError } = useGetRoutesWithRange();
  const routeNames = data.map((r) => r.routeName);

  const selectedRoutes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];

  const handleChange = (values) => {
    setSearchParams((prev) => {
      if (values.length === 0) {
        prev.delete('routes');
      } else {
        prev.set('routes', values.join(','));
      }
      return prev;
    });
  };

  if (!projectUuid) {
    return (
      <Select
        disabled
        id={id}
        placeholder="Select a project first"
        style={{ width: 250 }}
      />
    );
  }

  if (isError) {
    return (
      <Select
        disabled
        id={id}
        placeholder="Unable to load routes"
        style={{ width: 250 }}
      />
    );
  }

  return (
    <Select
      allowClear
      id={id}
      maxTagCount="responsive"
      mode="multiple"
      onChange={handleChange}
      options={routeNames.map((name) => ({ label: name, value: name }))}
      placeholder="All routes"
      showSearch
      style={{ width: 250 }}
      value={selectedRoutes}
    />
  );
}

function RequestTypeSelector({ id }) {
  const [searchParams, setSearchParams] = useSearchParams();

  const selectedRequestTypes = searchParams.get('requestType')
    ? searchParams.get('requestType').split(',')
    : [];

  const handleOnChange = (values) => {
    setSearchParams((prev) => {
      if (values.length === 0) {
        prev.delete('requestType');
      } else {
        prev.set('requestType', values.join(','));
      }
      return prev;
    });
  };

  return (
    <Select
      allowClear
      id={id}
      maxTagCount="responsive"
      mode="multiple"
      onChange={handleOnChange}
      options={REQUEST_TYPE_OPTIONS}
      placeholder="All types"
      style={{ width: 250 }}
      value={selectedRequestTypes}
    />
  );
}

export default TracingListHeader;
