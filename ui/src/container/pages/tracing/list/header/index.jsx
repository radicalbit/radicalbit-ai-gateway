import { TimeFilterCustomOnly } from '@Components/time-filter';
import { faRoute } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon, FormField, NewHeader, SectionTitle, Select } from '@radicalbit/radicalbit-design-system';
import { useGetRoutesWithRange } from '@Src/store/state/routes/vertical-hooks';
import { useSearchParams } from 'react-router-dom';
import ProjectFilter from './project-filter';

const keys = ['routes', 'preset', 'from', 'to'];
const storageKey = 'rbit-gw-tracing';

function TracingListHeader() {
  return (
    <NewHeader
      details={{
        one: (
          <div className="flex flex-row items-center gap-4">
            <FormField label="Project">
              <ProjectFilter />
            </FormField>

            <FormField label="Routes">
              <RouteSelector />
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
          titlePrefix={<FontAwesomeIcon icon={faRoute} />}
        />
      )}
    />
  );
}

function RouteSelector() {
  const [searchParams, setSearchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const { data = [] } = useGetRoutesWithRange();
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
        placeholder="Select a project first"
        style={{ width: 400 }}
      />
    );
  }

  return (
    <Select
      allowClear
      maxTagCount="responsive"
      mode="multiple"
      onChange={handleChange}
      options={routeNames.map((name) => ({ label: name, value: name }))}
      placeholder="All routes"
      style={{ width: 400 }}
      value={selectedRoutes}
    />
  );
}

export default TracingListHeader;
