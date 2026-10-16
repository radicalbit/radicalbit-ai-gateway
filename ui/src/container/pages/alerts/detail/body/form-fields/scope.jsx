import {
  ALERT_SCOPE_LABELS, AlertScopeEnum, AlertTimeAggregationEnum,
} from '@Src/constants';
import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Select } from '@radicalbit/radicalbit-design-system';
import { useId } from 'react';

const SCOPE_OPTIONS = Object.values(AlertScopeEnum).map((value) => ({
  label: ALERT_SCOPE_LABELS[value],
  value,
}));

function Scope() {
  const id = useId();

  const { form, write } = useFormbitContext();
  const scope = form?.scope;

  const handleOnChange = (value) => {
    write('scope', value);
    write('project', undefined);
    write('credential', undefined);
    write('route', undefined);
    write('event', undefined);
    write('timeAggregation', AlertTimeAggregationEnum.INSTANT);
    write('windowSize', undefined);
  };

  return (
    <FormField htmlFor={id} label="Scope">
      <Select id={id} onChange={handleOnChange} options={SCOPE_OPTIONS} value={scope} />
    </FormField>
  );
}

export default Scope;
