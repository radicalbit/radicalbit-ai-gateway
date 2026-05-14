import { useGetEventsByRouteWithRange } from '@Src/store/state/routes/vertical-hooks';
import { DataTable } from '@radicalbit/radicalbit-design-system';
import { useParams } from 'react-router-dom';
import columns from './columns';

function Fallbacks() {
  const { name } = useParams();

  const { data, isLoading } = useGetEventsByRouteWithRange(name);
  const fallbacks = data?.fallbacks;

  return (
    <DataTable
      columns={columns}
      dataSource={fallbacks}
      loading={isLoading}
      pagination={{
        hideOnSinglePage: true,
      }}
      rowKey="timestamp"
    />
  );
}

export default Fallbacks;
