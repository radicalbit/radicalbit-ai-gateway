import { useGetTraceByIdVertical } from '@State/tracing/vertical-hooks';
import { Board } from '@radicalbit/radicalbit-design-system';
import SpanDetail, { SpanHeader } from './span-detail';
import TreeComponent from './tree-component';

function Body({ traceId }) {
  const { data } = useGetTraceByIdVertical(traceId);
  const { tree } = data;

  if (!tree) {
    return (
      <div className="flex items-center justify-center h-full p-8">
        <span>No span tree available for this trace.</span>
      </div>
    );
  }

  return (
    <div className="flex flex-row h-full">
      <Board
        className="basis-1/5 grow min-w-0"
        main={<TreeComponent traceId={traceId} tree={tree} />}
        overflow="auto"
      />

      <Board
        className="basis-4/5 grow min-w-0"
        header={<SpanHeader traceId={traceId} />}
        main={<SpanDetail traceId={traceId} />}
      />
    </div>
  );
}

export default Body;
