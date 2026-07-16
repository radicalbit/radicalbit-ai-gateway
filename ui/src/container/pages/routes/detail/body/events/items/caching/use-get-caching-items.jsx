import Lucide from '@Components/lucide';
import { useGetEventsByRouteWithRange } from '@Src/store/state/routes/vertical-hooks';
import { Button } from '@radicalbit/radicalbit-design-system';
import { CircleCheck } from 'lucide-react';
import { useParams } from 'react-router-dom';

const useGetCachingItem = () => {
  const { name } = useParams();

  const { data } = useGetEventsByRouteWithRange(name);
  const cacheTriggered = data?.cacheTriggered;

  const type = (function getType() {
    if (cacheTriggered === undefined) {
      return { disabled: true };
    }
    if (cacheTriggered.length === 0) {
      return { type: 'primary-light' };
    }
    return { type: 'primary' };
  }());

  const collapseProps = !cacheTriggered?.length
    ? { collapsible: 'disabled', showArrow: false }
    : {};

  return {
    ...collapseProps,
    label: (
      <div className="flex justify-start items-center gap-4">
        <Button shape="circle" {...type}>
          <Lucide icon={CircleCheck} />
        </Button>

        <div>Caching</div>
      </div>
    ),
  };
};

export default useGetCachingItem;
