import IconBadge from '@Components/icon-badge';
import Lucide from '@Components/lucide';
import { SecretStatusEnum } from '@Src/constants';
import { Tooltip } from '@radicalbit/radicalbit-design-system';
import { TriangleAlert } from 'lucide-react';

function Status({ status }) {
  if (status !== SecretStatusEnum.UNAVAILABLE) {
    return false;
  }

  return (
    <Tooltip title="Unavailable: a published configuration references this key, but the secrets backend no longer holds it">
      <IconBadge aria-label="Status: unavailable" size="small" type="error">
        <Lucide icon={TriangleAlert} />
      </IconBadge>
    </Tooltip>
  );
}

export default Status;
