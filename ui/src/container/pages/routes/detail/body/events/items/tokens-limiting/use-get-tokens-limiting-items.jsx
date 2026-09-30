import IconBadge from '@Components/icon-badge';
import Lucide from '@Components/lucide';
import { useGetEventsByRouteWithRange, useGetRouteByNameWithRange } from '@Src/store/state/routes/vertical-hooks';
import isEmpty from 'lodash/isEmpty';
import { TableColumnsSplit } from 'lucide-react';
import { useParams } from 'react-router-dom';

const useGetTokensLimitingItem = () => {
  const { name } = useParams();

  const { data } = useGetEventsByRouteWithRange(name);
  const { data: route } = useGetRouteByNameWithRange(name);

  const tokenInputLimit = data?.tokenInputLimit;
  const tokenOutputLimit = data?.tokenOutputLimit;
  const chatModels = route?.configuration?.chatModels;
  const embeddingModels = route?.configuration?.embeddingModels;

  if (isEmpty(chatModels) && isEmpty(embeddingModels)) {
    return { hidden: true };
  }

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
        <IconBadge aria-label="Token Limiting" {...type}><Lucide icon={TableColumnsSplit} /></IconBadge>

        <div>Token Limiting</div>
      </div>
    ),
  };
};

export default useGetTokensLimitingItem;
