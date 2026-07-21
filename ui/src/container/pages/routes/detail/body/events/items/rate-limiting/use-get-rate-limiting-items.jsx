import Lucide from '@Components/lucide';
import { useGetEventsByRouteWithRange } from '@Src/store/state/routes/vertical-hooks';
import { Button } from '@radicalbit/radicalbit-design-system';
import { Timer } from 'lucide-react';
import { useParams } from 'react-router-dom';

const useGetRateLimitingItem = () => {
  const { name } = useParams();

  const { data } = useGetEventsByRouteWithRange(name);
  const rateLimit = data?.rateLimit;

  const type = (function getType() {
    if (rateLimit === undefined) {
      return { disabled: true };
    }
    if (rateLimit.length === 0) {
      return { type: 'primary-light' };
    }
    return { type: 'primary' };
  }());

  const collapseProps = !rateLimit?.length
    ? { collapsible: 'disabled', showArrow: false }
    : {};

  return {
    ...collapseProps,
    label: (
      <div className="flex justify-start items-center gap-4">
        <Button shape="circle" {...type}><Lucide icon={Timer} /></Button>

        <div>Rate Limiting</div>
      </div>
    ),
  };
};

export default useGetRateLimitingItem;
