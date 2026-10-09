import IconBadge from '@Components/icon-badge';
import Lucide from '@Components/lucide';
import { SecretStatusEnum } from '@Src/constants';
import { TriangleAlert } from 'lucide-react';

function Status({ status }) {
  if (status !== SecretStatusEnum.UNAVAILABLE) {
    return false;
  }

  return (
    <IconBadge aria-label="Status: unavailable" size="small" type="error">
      <Lucide icon={TriangleAlert} />
    </IconBadge>
  );
}

export default Status;
