import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import { useGetTraceLatenciesWithRange } from '@Src/store/state/tracing/vertical-hooks';
import { Board, DataTable, SectionTitle, Skeleton, Void } from '@radicalbit/radicalbit-design-system';
import columns from './columns';

function TraceLatencies() {
  const { data, isError, isLoading, isSuccess } = useGetTraceLatenciesWithRange();

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
    return (
      <Board
        header={<SectionTitle title="Trace latencies" />}
        main={<SomethingWentWrong size="small" />}
      />
    );
  }

  if (!data) {
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

  if (!isSuccess) {
    return null;
  }

  return (
    <Board
      header={<SectionTitle title="Trace latencies" />}
      main={(
        <DataTable
          columns={columns}
          dataSource={[data]}
          pagination={false}
          rowKey="trace-latencies"
        />
      )}
    />
  );
}

export default TraceLatencies;
