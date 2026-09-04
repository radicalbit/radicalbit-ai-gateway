import { useGetEventsByRouteWithRange } from '@Src/store/state/routes/vertical-hooks';
import { DataTable } from '@radicalbit/radicalbit-design-system';
import { useParams } from 'react-router-dom';
import columns from './columns';

function DurationLimiting() {
  const { name } = useParams();

  const { data, isLoading } = useGetEventsByRouteWithRange(name);
  const durationLimit = data?.durationLimit;

  return (
    <DataTable
      columns={columns}
      dataSource={durationLimit}
      loading={isLoading}
      pagination={{
        hideOnSinglePage: true,
      }}
      rowKey="timestamp"
    />
  );
}

export default DurationLimiting;
