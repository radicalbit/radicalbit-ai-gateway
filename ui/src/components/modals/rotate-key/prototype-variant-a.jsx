// PROTOTYPE (AG-1041) — Modal variant A, "Radio + fields": Grace period (number + unit) or No grace period.
import {
  formatInstant, getDefaultGrace, getGraceEnd,
} from '@Container/pages/keys/list/body/prototype-rotation/mock-rotation';
import {
  FormField, InputNumber, Radio, Select, Tooltip,
} from '@radicalbit/radicalbit-design-system';

const UNIT_OPTIONS = [{ label: 'hours', value: 'hours' }, { label: 'days', value: 'days' }, { label: 'weeks', value: 'weeks' }];

const NO_GRACE_ONLY_TOOLTIP = 'The credential expires in less than 1 hour: only no grace period is possible';

function VariantA({ error, expiryInstant, grace, noGraceOnly, onChange }) {
  const isGrace = grace.mode === 'grace';

  const handleOnChangeMode = ({ target: { value } }) => {
    onChange(value === 'none' ? { mode: 'none' } : { mode: 'grace', ...getDefaultGrace(expiryInstant) });
  };

  const handleOnChangeAmount = (amount) => {
    onChange({ ...grace, amount });
  };

  const handleOnChangeUnit = (unit) => {
    onChange({ ...grace, unit });
  };

  const graceRadio = noGraceOnly
    ? <Tooltip title={NO_GRACE_ONLY_TOOLTIP}><span><Radio disabled value="grace">Grace period</Radio></span></Tooltip>
    : <Radio value="grace">Grace period</Radio>;

  const fields = isGrace ? (
    <div className="flex gap-2">
      <InputNumber min={1} onChange={handleOnChangeAmount} precision={0} value={grace.amount} />

      <Select onChange={handleOnChangeUnit} options={UNIT_OPTIONS} style={{ width: 120 }} value={grace.unit} />
    </div>
  ) : false;

  const help = (() => {
    if (!isGrace) return 'The previous value stops working immediately.';
    if (error) return false;
    return `Both values work until ${formatInstant(getGraceEnd(grace))}.`;
  })();

  return (
    <FormField label="Previous value" message={isGrace ? error : undefined}>
      <div className="flex flex-col gap-2">
        <Radio.Group onChange={handleOnChangeMode} value={grace.mode}>
          {graceRadio}

          <Radio value="none">No grace period</Radio>
        </Radio.Group>

        {fields}

        <span className="text-xs opacity-70">{help}</span>
      </div>
    </FormField>
  );
}

export default VariantA;
