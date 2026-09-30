import IconBadge from '@Components/icon-badge';
import Lucide from '@Components/lucide';
import { useGetEventsByRouteWithRange } from '@Src/store/state/routes/vertical-hooks';
import { Shield } from 'lucide-react';
import { useParams } from 'react-router-dom';

const useGetGuardrailsItem = () => {
  const { name } = useParams();

  const { data } = useGetEventsByRouteWithRange(name);
  const guardrails = data?.guardrails;

  const type = (function getType() {
    if (guardrails === undefined) {
      return { disabled: true };
    }
    if (guardrails.length === 0) {
      return { type: 'primary-light' };
    }
    return { type: 'primary' };
  }());

  const collapseProps = !guardrails?.length
    ? { collapsible: 'disabled', showArrow: false }
    : {};

  return {
    ...collapseProps,
    label: (
      <div className="flex justify-start items-center gap-4">
        <IconBadge aria-label="Guardrails" {...type}><Lucide icon={Shield} /></IconBadge>

        <div>Guardrails</div>
      </div>
    ),
  };
};

export default useGetGuardrailsItem;
