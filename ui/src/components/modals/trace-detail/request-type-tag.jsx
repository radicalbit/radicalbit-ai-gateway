import useModals from '@Hooks/use-modals';
import { REQUEST_TYPE_LABELS } from '@Src/constants';
import { useGetTraceByIdVertical } from '@State/tracing/vertical-hooks';
import { Tag } from '@radicalbit/radicalbit-design-system';

function RequestTypeTag() {
  const { modalPayload } = useModals();
  const traceId = modalPayload?.data?.traceId;

  const { data } = useGetTraceByIdVertical(traceId);
  const requestType = data?.requestType;

  const label = REQUEST_TYPE_LABELS[requestType];

  if (!label) {
    return false;
  }

  return <Tag type="primary-outlined">{label}</Tag>;
}

export default RequestTypeTag;
