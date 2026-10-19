// PROTOTYPE (AG-1041) — Modal variant E, the chosen combination: radio Grace period / No grace period (A);
// with Grace period, the presets bar of B (shrunk to its content), and Custom opens a narrow number + unit.
import {
  UNIT_MS, formatInstant, getDefaultGrace, getGraceEnd,
} from '@Container/pages/keys/list/body/prototype-rotation/mock-rotation';
import {
  FormField, InputNumber, Radio, Segmented, Select, Tooltip,
} from '@radicalbit/radicalbit-design-system';
import { useState } from 'react';

const UNIT_OPTIONS = [{ label: 'hours', value: 'hours' }, { label: 'days', value: 'days' }, { label: 'weeks', value: 'weeks' }];

const PRESETS = {
  '1 hour': { amount: 1, unit: 'hours' },
  '24 hours': { amount: 24, unit: 'hours' },
  '7 days': { amount: 7, unit: 'days' },
};

const CUSTOM = 'Custom';

const NO_GRACE_ONLY_TOOLTIP = 'The credential expires in less than 1 hour: only no grace period is possible';

const fits = ({ amount, unit }, expiryInstant) => expiryInstant === null || Date.now() + amount * UNIT_MS[unit] <= expiryInstant;

const findPreset = ({ amount, unit }) => Object.keys(PRESETS).find((k) => PRESETS[k].amount === amount && PRESETS[k].unit === unit) ?? CUSTOM;

function VariantE({ error, expiryInstant, grace, noGraceOnly, onChange }) {
  const [preset, setPreset] = useState(grace.mode === 'grace' ? findPreset(grace) : '24 hours');

  const isGrace = grace.mode === 'grace';
  const isCustom = preset === CUSTOM;

  const options = [
    ...Object.keys(PRESETS).map((label) => ({ label, value: label, disabled: !fits(PRESETS[label], expiryInstant) })),
    { label: CUSTOM, value: CUSTOM },
  ];

  const handleOnChangeMode = ({ target: { value } }) => {
    if (value === 'none') {
      onChange({ mode: 'none' });
      return;
    }
    const defaultGrace = getDefaultGrace(expiryInstant);
    setPreset(findPreset(defaultGrace));
    onChange({ mode: 'grace', ...defaultGrace });
  };

  const handleOnChangePreset = (value) => {
    setPreset(value);
    if (value !== CUSTOM) {
      onChange({ mode: 'grace', ...PRESETS[value] });
    }
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

  // w-0 min-w-full: the row never widens the group, it only fills the presets bar's width.
  // The design system forces its own widths: width 100% inside flex-1 wrappers splits the row 50/50
  const customFields = isCustom ? (
    <div className="flex gap-2 w-0 min-w-full">
      <div className="flex-1 min-w-0">
        <InputNumber min={1} onChange={handleOnChangeAmount} precision={0} style={{ width: '100%' }} value={grace.amount} />
      </div>

      <div className="flex-1 min-w-0">
        <Select onChange={handleOnChangeUnit} options={UNIT_OPTIONS} popupMatchSelectWidth={false} style={{ width: '100%' }} value={grace.unit} />
      </div>
    </div>
  ) : false;

  // inline-flex: the group takes the presets bar's width, and the Custom row stretches to it
  const graceDetails = isGrace ? (
    <div className="inline-flex flex-col gap-2 self-start">
      <Segmented onChange={handleOnChangePreset} options={options} value={preset} />

      {customFields}
    </div>
  ) : false;

  const help = (() => {
    if (!isGrace) return 'The previous value stops working immediately.';
    if (error) return false;
    return `Both values work until ${formatInstant(getGraceEnd(grace))}.`;
  })();

  return (
    <FormField message={isGrace ? error : undefined}>
      <div className="flex flex-col gap-2">
        <Radio.Group onChange={handleOnChangeMode} value={grace.mode}>
          {graceRadio}

          <Radio value="none">No grace period</Radio>
        </Radio.Group>

        {graceDetails}

        <span className="text-xs opacity-70">{help}</span>
      </div>
    </FormField>
  );
}

export default VariantE;
