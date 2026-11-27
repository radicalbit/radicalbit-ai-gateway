import IconBadge from '@Components/icon-badge';
import Lucide from '@Components/lucide';
import { useGetEventsByRouteWithRange } from '@Src/store/state/routes/vertical-hooks';
import { Timer } from 'lucide-react';
import { useParams } from 'react-router-dom';

// Credential and project limits apply whatever the route configures, so the section is always there.
const useGetLimitsItem = () => {
  const { name } = useParams();

  const { data } = useGetEventsByRouteWithRange(name);
  const limits = data?.limits;

  if (!limits?.length) {
    return {
      collapsible: 'disabled',
      showArrow: false,
      label: <LimitsLabel type="primary-light" />,
    };
  }

  return {
    label: <LimitsLabel type="primary" />,
  };
};

function LimitsLabel({ type }) {
  return (
    <div className="flex justify-start items-center gap-4">
      <IconBadge aria-label="Limits" type={type}><Lucide icon={Timer} /></IconBadge>

      <div>Limits</div>
    </div>
  );
}

export default useGetLimitsItem;
