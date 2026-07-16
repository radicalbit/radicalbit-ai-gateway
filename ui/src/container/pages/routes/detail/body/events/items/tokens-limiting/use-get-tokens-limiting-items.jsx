import Lucide from '@Components/lucide';
import { useGetEventsByRouteWithRange } from '@Src/store/state/routes/vertical-hooks';
import { Button } from '@radicalbit/radicalbit-design-system';
import { TableColumnsSplit } from 'lucide-react';
import { useParams } from 'react-router-dom';

const useGetTokensLimitingItem = () => {
  const { name } = useParams();

  const { data } = useGetEventsByRouteWithRange(name);
  const tokenInputLimit = data?.tokenInputLimit;
  const tokenOutputLimit = data?.tokenOutputLimit;

  const type = (function getType() {
    if (tokenInputLimit === undefined && tokenOutputLimit === undefined) {
      return { disabled: true };
    }
    if (tokenInputLimit?.length === 0 && tokenOutputLimit?.length === 0) {
      return { type: 'primary-light' };
    }
    return { type: 'primary' };
  }());

  const collapseProps = !tokenInputLimit?.length && !tokenOutputLimit?.length
    ? { collapsible: 'disabled', showArrow: false }
    : {};

  return {
    ...collapseProps,
    label: (
      <div className="flex justify-start items-center gap-4">
        <Button shape="circle" {...type}><Lucide icon={TableColumnsSplit} /></Button>

        <div>Token Limiting</div>
      </div>
    ),
  };
};

export default useGetTokensLimitingItem;
