import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import { useGetTraceLatenciesWithRange } from '@Src/store/state/tracing/vertical-hooks';
import { Board, DataTable, SectionTitle, Skeleton, Void } from '@radicalbit/radicalbit-design-system';
import columns from './columns';

function TraceLatencies() {
  const { data, isError, isFetching, isLoading, isSuccess } = useGetTraceLatenciesWithRange();

  if (isLoading) {
    return (
      <Board
        header={<SectionTitle title="Trace latencies" />}
        main={(
          <Skeleton.Input active block />
        )}
      />
    );
  }

  if (isError) {
    return <IsError />;
  }

  if (!data) {
    return <IsEmpty />;
  }

  if (!isSuccess) {
    return null;
  }

  const dataSource = isFetching ? [{}] : [data];

  return (
    <Board
      header={<SectionTitle title="Trace latencies" />}
      main={(
        <DataTable
          columns={columns}
          dataSource={dataSource}
          pagination={false}
          rowKey="trace-latencies"
        />
      )}
    />
  );
}

function IsError() {
  return (
    <Board
      header={<SectionTitle title="Trace latencies" />}
      main={<SomethingWentWrong size="small" />}
    />
  );
}

function IsEmpty() {
  return (
    <Board
      header={<SectionTitle title="Trace latencies" />}
      main={(
        <Void
          description="No trace latency data available yet."
          title="Trace latencies"
        />
      )}
    />
  );
}

export default TraceLatencies;
