import { useGetRoutesWithRange } from '@Src/store/state/routes/vertical-hooks';
import { Select } from '@radicalbit/radicalbit-design-system';
import { useSearchParams } from 'react-router-dom';

function RoutesFilter({ id }) {
  const [searchParams, setSearchParams] = useSearchParams();

  const { data = [], isError } = useGetRoutesWithRange();
  const routeNames = data.map((r) => r.routeName);

  const selectedRoutes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];

  const handleOnChange = (values) => {
    setSearchParams((prev) => {
      if (values.length === 0) {
        prev.delete('routes');
      } else {
        prev.set('routes', values.join(','));
      }
      return prev;
    });
  };

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
      onChange={handleOnChange}
      options={routeNames.map((name) => ({ label: name, value: name }))}
      placeholder="All routes"
      showSearch
      style={{ width: 250 }}
      value={selectedRoutes}
    />
  );
}

export default RoutesFilter;
