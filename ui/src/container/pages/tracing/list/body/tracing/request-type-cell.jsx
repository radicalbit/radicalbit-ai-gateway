import { REQUEST_TYPE_LABELS } from '@Src/constants';
import { Tag } from '@radicalbit/radicalbit-design-system';

function RequestTypeCell({ requestType }) {
  const label = REQUEST_TYPE_LABELS[requestType];

  if (!label) {
    return '--';
  }

  return <Tag size="large" type="primary-outlined">{label}</Tag>;
}

export default RequestTypeCell;
