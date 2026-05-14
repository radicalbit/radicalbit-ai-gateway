import { useGetEventsByRouteWithRange } from '@Src/store/state/routes/vertical-hooks';
import { DataTable } from '@radicalbit/radicalbit-design-system';
import { useParams } from 'react-router-dom';
import columns from './columns';

function Caching() {
  const { name } = useParams();

  const { data, isLoading } = useGetEventsByRouteWithRange(name);
  const cacheTriggered = data?.cacheTriggered;

  return (
    <DataTable
      columns={columns}
      dataSource={cacheTriggered}
      loading={isLoading}
      pagination={{
        hideOnSinglePage: true,
      }}
      rowKey="timestamp"
    />
  );
}

export default Caching;
