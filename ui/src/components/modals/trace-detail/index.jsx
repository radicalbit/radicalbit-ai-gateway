import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import useModals from '@Hooks/use-modals';
import { useGetTraceByIdVertical } from '@State/tracing/vertical-hooks';
import { RbitModal, Skeleton } from '@radicalbit/radicalbit-design-system';
import Body from './body';
import Header from './header';

function TraceDetail() {
  const { hideModal, modalPayload } = useModals();
  const traceId = modalPayload?.data?.traceId;

  const { isLoading, isError, isSuccess } = useGetTraceByIdVertical(traceId);

  if (isLoading) {
    return (
      <RbitModal defaultMaximize onCancel={hideModal} open>
        <IsLoading />
      </RbitModal>
    );
  }

  if (isError) {
    return (
      <RbitModal defaultMaximize onCancel={hideModal} open>
        <IsError />
      </RbitModal>
    );
  }

  if (!isSuccess) {
    return null;
  }

  return (
    <RbitModal
      closable={false}
      defaultMaximize
      header={<Header />}
      onCancel={hideModal}
      open
    >
      <Body />
    </RbitModal>
  );
}

function IsLoading() {
  return (
    <div className="p-8">
      <Skeleton active block />
    </div>
  );
}

function IsError() {
  return (
    <div className="h-full">
      <SomethingWentWrong size="small" />
    </div>
  );
}

export default TraceDetail;
