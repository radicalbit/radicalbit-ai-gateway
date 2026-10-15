// PROTOTYPE (AG-1037) — Modal variant A, "Radio + picker": Never / On date, the DatePicker appears only for "On date".
import { DatePicker, FormField, Radio } from '@radicalbit/radicalbit-design-system';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import { useState } from 'react';

dayjs.extend(utc);

// Earliest selectable day = today in UTC, compared as a calendar date (not the browser's local day)
const todayUtc = () => dayjs.utc().format('YYYY-MM-DD');
const disabledDate = (d) => d.format('YYYY-MM-DD') < todayUtc();

function VariantA({ onChange }) {
  const [mode, setMode] = useState('never');
  const [date, setDate] = useState(null);

  const handleOnModeChange = ({ target: { value } }) => {
    setMode(value);
    onChange(value === 'never' ? null : date?.format('YYYY-MM-DD') ?? null);
  };

  const handleOnDateChange = (d) => {
    setDate(d);
    onChange(d ? d.format('YYYY-MM-DD') : null);
  };

  return (
    <FormField label="Expiration" message="Expires at the end of the chosen day (UTC)">
      <div className="flex flex-col gap-2">
        <Radio.Group onChange={handleOnModeChange} value={mode}>
          <Radio value="never">Never</Radio>

          <Radio value="date">On date</Radio>
        </Radio.Group>

        {mode === 'date' && (
          <DatePicker
            disabledDate={disabledDate}
            format="DD MMM YYYY"
            onChange={handleOnDateChange}
            placeholder="Select a date"
            style={{ width: '100%' }}
            value={date}
          />
        )}
      </div>
    </FormField>
  );
}

export default VariantA;
