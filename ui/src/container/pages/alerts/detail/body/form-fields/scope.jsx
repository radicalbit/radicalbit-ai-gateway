import { ALERT_SCOPE_LABELS, AlertScopeEnum } from '@Src/constants';
import { FormField, Select } from '@radicalbit/radicalbit-design-system';

const SCOPE_OPTIONS = Object.values(AlertScopeEnum).map((value) => ({
  label: ALERT_SCOPE_LABELS[value],
  value,
}));

function Scope() {
  return (
    <FormField label="Scope">
      <Select disabled options={SCOPE_OPTIONS} value={AlertScopeEnum.ROUTE} />
    </FormField>
  );
}

export default Scope;
