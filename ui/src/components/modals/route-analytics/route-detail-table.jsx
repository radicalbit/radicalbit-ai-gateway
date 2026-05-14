import { useGetRouteByNameWithRange } from '@Src/store/state/routes/vertical-hooks';
import { Board, DataTable, Void } from '@radicalbit/radicalbit-design-system';
import columns from './columns';

function RouteDetailTable({ routeName }) {
  const { data, isLoading, isError } = useGetRouteByNameWithRange(routeName);

  if (isError) {
    return <IsError />;
  }

  return (
    <DataTable
      columns={columns}
      dataSource={data ? [data] : []}
      loading={isLoading}
      pagination={false}
      rowKey={({ routeName: name }) => name}
    />
  );
}

function IsError() {
  return (
    <Board
      main={(
        <Void
          description={(
            <>
              Unable to load route details. Please try again later.
            </>
          )}
          size="small"
          title="Something went wrong"
        />
      )}
      size="small"
    />
  );
}

export default RouteDetailTable;
