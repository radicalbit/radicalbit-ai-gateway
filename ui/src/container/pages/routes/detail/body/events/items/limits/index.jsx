import { useGetEventsByRouteWithRange } from '@Src/store/state/routes/vertical-hooks';
import { DataTable } from '@radicalbit/radicalbit-design-system';
import { useParams } from 'react-router-dom';
import columns from './columns';

// Route and credential limits can block the same request at the same instant.
const getRowKey = ({ apiKeyUuid, eventType, timestamp }) => `${timestamp}|${eventType}|${apiKeyUuid}`;

function Limits() {
  const { name } = useParams();

  const { data, isLoading } = useGetEventsByRouteWithRange(name);
  const limits = data?.limits;

  return (
    <DataTable
      columns={columns}
      dataSource={limits}
      loading={isLoading}
      pagination={{
        hideOnSinglePage: true,
      }}
      rowKey={getRowKey}
    />
  );
}

export default Limits;
