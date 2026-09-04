import Lucide from '@Components/lucide';
import { useGetEventsByRouteWithRange, useGetRouteByNameWithRange } from '@Src/store/state/routes/vertical-hooks';
import { Button } from '@radicalbit/radicalbit-design-system';
import isEmpty from 'lodash/isEmpty';
import { Hourglass } from 'lucide-react';
import { useParams } from 'react-router-dom';

const useGetDurationLimitingItem = () => {
  const { name } = useParams();

  const { data } = useGetEventsByRouteWithRange(name);
  const { data: route } = useGetRouteByNameWithRange(name);

  const durationLimit = data?.durationLimit;
  const transcriptionModels = route?.configuration?.transcriptionModels;

  if (isEmpty(transcriptionModels)) {
    return { hidden: true };
  }

  const type = (function getType() {
    if (durationLimit === undefined) {
      return { disabled: true };
    }
    if (durationLimit.length === 0) {
      return { type: 'primary-light' };
    }
    return { type: 'primary' };
  }());

  const collapseProps = !durationLimit?.length
    ? { collapsible: 'disabled', showArrow: false }
    : {};

  return {
    ...collapseProps,
    label: (
      <div className="flex justify-start items-center gap-4">
        <Button shape="circle" {...type}><Lucide icon={Hourglass} /></Button>

        <div>Duration Limiting</div>
      </div>
    ),
  };
};

export default useGetDurationLimitingItem;
