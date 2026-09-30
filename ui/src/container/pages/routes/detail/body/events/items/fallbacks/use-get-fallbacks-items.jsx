import IconBadge from '@Components/icon-badge';
import Lucide from '@Components/lucide';
import { useGetEventsByRouteWithRange } from '@Src/store/state/routes/vertical-hooks';
import { CornerDownRight } from 'lucide-react';
import { useParams } from 'react-router-dom';

const useGetFallbacksItem = () => {
  const { name } = useParams();

  const { data } = useGetEventsByRouteWithRange(name);
  const fallbacks = data?.fallbacks;

  const type = (function getType() {
    if (fallbacks === undefined) {
      return { disabled: true };
    }
    if (fallbacks.length === 0) {
      return { type: 'primary-light' };
    }
    return { type: 'primary' };
  }());

  const collapseProps = !fallbacks?.length
    ? { collapsible: 'disabled', showArrow: false }
    : {};

  return {
    ...collapseProps,
    label: (
      <div className="flex justify-start items-center gap-4">
        <IconBadge aria-label="Fallback" {...type}><Lucide icon={CornerDownRight} /></IconBadge>

        <div>Fallback</div>
      </div>
    ),
  };
};

export default useGetFallbacksItem;
