import { useGetEventsByRouteWithRange } from '@Src/store/state/routes/vertical-hooks';
import { DataTable } from '@radicalbit/radicalbit-design-system';
import { useParams } from 'react-router-dom';
import columns from './columns';

function TokensLimiting() {
  const { name } = useParams();

  const { data, isLoading } = useGetEventsByRouteWithRange(name);
  const tokenInputLimit = data?.tokenInputLimit;
  const tokenOutputLimit = data?.tokenOutputLimit;

  const tokenLimit = tokenInputLimit
    .map((e) => ({ type: 'IN', ...e }))
    .concat(tokenOutputLimit
      .map((e) => ({ type: 'OUT', ...e })));

  return (
    <DataTable
      columns={columns}
      dataSource={tokenLimit}
      loading={isLoading}
      pagination={{
        hideOnSinglePage: true,
      }}
      rowKey="timestamp"
    />
  );
}

export default TokensLimiting;
