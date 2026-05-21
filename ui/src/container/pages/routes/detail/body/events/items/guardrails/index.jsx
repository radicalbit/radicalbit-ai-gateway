import { useGetEventsByRouteWithRange } from '@Src/store/state/routes/vertical-hooks';
import { DataTable } from '@radicalbit/radicalbit-design-system';
import { useParams } from 'react-router-dom';
import columns from './columns';

function Guardrails() {
  const { name } = useParams();

  const { data, isLoading } = useGetEventsByRouteWithRange(name);
  const guardrails = data?.guardrails;

  return (
    <DataTable
      columns={columns}
      dataSource={guardrails}
      loading={isLoading}
      pagination={{
        hideOnSinglePage: true,
      }}
      rowKey="timestamp"
    />
  );
}

export default Guardrails;
