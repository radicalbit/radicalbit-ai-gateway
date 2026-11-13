import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import Lucide from '@Components/lucide';
import useModals from '@Hooks/use-modals';
import { useGetRequestByIdVertical } from '@State/requests/vertical-hooks';
import { useGetTraceByIdVertical } from '@State/tracing/vertical-hooks';
import { Board, Skeleton, Void } from '@radicalbit/radicalbit-design-system';
import { Waypoints } from 'lucide-react';
import SpanPanel from './span-panel';
import Spans from './spans';

function Body() {
  const { modalPayload } = useModals();
  const requestUuid = modalPayload?.data?.requestUuid;

  const { data: request, isError: isRequestError, isLoading: isRequestLoading, isSuccess: isRequestSuccess } = useGetRequestByIdVertical(requestUuid);
  const traceId = request?.traceId;

  const { data: trace, isError: isTraceError, isLoading: isTraceLoading, isSuccess: isTraceSuccess } = useGetTraceByIdVertical(traceId);
  const tree = trace?.tree;

  if (isRequestLoading || isTraceLoading) {
    return <IsLoading />;
  }

  if (isRequestError || isTraceError) {
    return <SomethingWentWrong size="small" />;
  }

  if (isRequestSuccess && !traceId) {
    return <IsEmpty />;
  }

  if (isTraceSuccess && !tree) {
    return <IsEmpty />;
  }

  if (!isTraceSuccess) {
    return false;
  }

  return (
    <div className="flex flex-row items-start gap-4">
      <div className="basis-1/3 min-w-0">
        <Spans />
      </div>

      <div className="basis-2/3 min-w-0">
        <SpanPanel />
      </div>
    </div>
  );
}

function IsLoading() {
  return (
    <div className="flex flex-row items-start gap-4">
      <div className="basis-1/3">
        <Skeleton active block />
      </div>

      <div className="basis-2/3">
        <Skeleton active block />
      </div>
    </div>
  );
}

function IsEmpty() {
  return (
    <Board
      main={(
        <Void
          description="The gateway did not record a trace for this request."
          image={<Lucide icon={Waypoints} />}
          size="small"
          title="No trace for this request"
        />
      )}
      width="100%"
    />
  );
}

export default Body;
