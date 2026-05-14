import { useGetEventsByRouteWithRange } from '@Src/store/state/routes/vertical-hooks';
import { DataTable } from '@radicalbit/radicalbit-design-system';
import { useParams } from 'react-router-dom';
import columns from './columns';

function RateLimiting() {
  const { name } = useParams();

  const { data, isLoading } = useGetEventsByRouteWithRange(name);
  const rateLimit = data?.rateLimit;

  return (
    <DataTable
      columns={columns}
      dataSource={rateLimit}
      loading={isLoading}
      pagination={{
        hideOnSinglePage: true,
      }}
      rowKey="timestamp"
    />
  );
}

export default RateLimiting;
