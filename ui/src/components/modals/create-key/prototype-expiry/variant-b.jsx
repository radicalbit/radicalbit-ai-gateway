// PROTOTYPE (AG-1037) — Modal variant B, "Single picker": one DatePicker, empty = Never, presets in the panel.
import { DatePicker, FormField } from '@radicalbit/radicalbit-design-system';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import { useState } from 'react';

dayjs.extend(utc);

const todayUtc = () => dayjs.utc().format('YYYY-MM-DD');
const disabledDate = (d) => d.format('YYYY-MM-DD') < todayUtc();

// Local dayjs built from the UTC calendar date, so the picker highlights the right day
const fromUtcToday = (days) => dayjs(todayUtc(), 'YYYY-MM-DD').add(days, 'day');

const PRESETS = [
  { label: 'Today', value: fromUtcToday(0) },
  { label: '+7 days', value: fromUtcToday(7) },
  { label: '+30 days', value: fromUtcToday(30) },
  { label: '+90 days', value: fromUtcToday(90) },
  { label: '+1 year', value: fromUtcToday(365) },
];

function VariantB({ onChange }) {
  const [date, setDate] = useState(null);

  const handleOnChange = (d) => {
    setDate(d);
    onChange(d ? d.format('YYYY-MM-DD') : null);
  };

  return (
    <FormField
      label="Expiration"
      message={date ? 'Expires at the end of the chosen day (UTC)' : 'Leave empty for a credential that never expires'}
    >
      <DatePicker
        allowClear
        disabledDate={disabledDate}
        format="DD MMM YYYY"
        onChange={handleOnChange}
        placeholder="Never"
        presets={PRESETS}
        style={{ width: '100%' }}
        value={date}
      />
    </FormField>
  );
}

export default VariantB;
