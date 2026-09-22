import { useGetProjectRoutesWithRange } from '@State/usage/vertical-hooks';
import { Select, Skeleton } from '@radicalbit/radicalbit-design-system';
import { useSearchParams } from 'react-router-dom';

function RoutesFilter() {
  const [searchParams, setSearchParams] = useSearchParams();

  const { data = [], isError, isLoading } = useGetProjectRoutesWithRange();

  if (isLoading) {
    return <Skeleton.Input active block />;
  }

  const routeNames = data.map((r) => r.routeName);
  const options = routeNames.map((name) => ({ label: name, value: name }));
  const selectedRoutes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];

  const placeholder = isError ? 'Unable to load routes' : 'Please select';

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

  return (
    <Select
      allowClear
      disabled={isError}
      maxTagCount="responsive"
      mode="multiple"
      onChange={handleOnChange}
      options={options}
      placeholder={placeholder}
      showSearch
      style={{ width: 400 }}
      value={selectedRoutes}
    />
  );
}

export default RoutesFilter;
