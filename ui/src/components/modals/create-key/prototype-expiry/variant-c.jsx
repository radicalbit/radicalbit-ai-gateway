// PROTOTYPE (AG-1037) — Modal variant C, "Duration presets": a Select of durations, Custom… opens a picker,
// and the resulting date is spelled out underneath.
import { DatePicker, FormField, Select } from '@radicalbit/radicalbit-design-system';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import { useState } from 'react';

dayjs.extend(utc);

const todayUtc = () => dayjs.utc().format('YYYY-MM-DD');
const disabledDate = (d) => d.format('YYYY-MM-DD') < todayUtc();
const addDaysUtc = (days) => dayjs.utc(todayUtc()).add(days, 'day').format('YYYY-MM-DD');

const OPTIONS = [
  { label: 'Never', value: 'never' },
  { label: '7 days', value: '7' },
  { label: '30 days', value: '30' },
  { label: '90 days', value: '90' },
  { label: '1 year', value: '365' },
  { label: 'Custom…', value: 'custom' },
];

function VariantC({ onChange }) {
  const [option, setOption] = useState('never');
  const [customDate, setCustomDate] = useState(null);

  const expiresOn = (() => {
    if (option === 'never') return null;
    if (option === 'custom') return customDate?.format('YYYY-MM-DD') ?? null;
    return addDaysUtc(Number(option));
  })();

  const handleOnOptionChange = (value) => {
    setOption(value);
    if (value === 'never') onChange(null);
    else if (value === 'custom') onChange(customDate?.format('YYYY-MM-DD') ?? null);
    else onChange(addDaysUtc(Number(value)));
  };

  const handleOnDateChange = (d) => {
    setCustomDate(d);
    onChange(d ? d.format('YYYY-MM-DD') : null);
  };

  const message = expiresOn
    ? `Expires on ${dayjs(expiresOn, 'YYYY-MM-DD').format('DD MMM YYYY')}, 23:59:59 UTC`
    : 'The credential never expires';

  return (
    <FormField label="Expiration" message={message}>
      <div className="flex gap-2">
        <Select onChange={handleOnOptionChange} options={OPTIONS} style={{ width: option === 'custom' ? '40%' : '100%' }} value={option} />

        {option === 'custom' && (
          <DatePicker
            disabledDate={disabledDate}
            format="DD MMM YYYY"
            onChange={handleOnDateChange}
            placeholder="Select a date"
            style={{ flex: 1 }}
            value={customDate}
          />
        )}
      </div>
    </FormField>
  );
}

export default VariantC;
