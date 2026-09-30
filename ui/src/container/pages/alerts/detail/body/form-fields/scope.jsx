import { ALERT_SCOPE_LABELS, AlertScopeEnum } from '@Src/constants';
import { FormField, Select } from '@radicalbit/radicalbit-design-system';
import { useId } from 'react';

const SCOPE_OPTIONS = Object.values(AlertScopeEnum).map((value) => ({
  label: ALERT_SCOPE_LABELS[value],
  value,
}));

function Scope() {
  const id = useId();

  return (
    <FormField htmlFor={id} label="Scope">
      <Select disabled id={id} options={SCOPE_OPTIONS} value={AlertScopeEnum.ROUTE} />
    </FormField>
  );
}

export default Scope;
