// PROTOTYPE (AG-1037) — Modal variant D, "Always-visible calendar": a "Never expires" checkbox (on by default)
// above an inline calendar that is disabled while the checkbox is on.
// NB: antd Calendar isn't re-exported by the design system — imported from antd directly, prototype only.
import { Checkbox, FormField } from '@radicalbit/radicalbit-design-system';
// eslint-disable-next-line import-x/no-extraneous-dependencies -- PROTOTYPE: antd is a transitive dep of the design system
import { Calendar } from 'antd';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import { useState } from 'react';

dayjs.extend(utc);

const todayUtc = () => dayjs.utc().format('YYYY-MM-DD');
const disabledDate = (d) => d.format('YYYY-MM-DD') < todayUtc();

function VariantD({ onChange }) {
  const [never, setNever] = useState(true);
  const [date, setDate] = useState(dayjs(todayUtc(), 'YYYY-MM-DD'));

  const handleOnNeverChange = ({ target: { checked } }) => {
    setNever(checked);
    onChange(checked ? null : date.format('YYYY-MM-DD'));
  };

  const handleOnSelect = (d) => {
    if (never) return;
    setDate(d);
    onChange(d.format('YYYY-MM-DD'));
  };

  const message = never
    ? 'The credential never expires'
    : `Expires on ${date.format('DD MMM YYYY')} at the end of the day (UTC)`;

  return (
    <FormField label="Expiration" message={message}>
      <div className="flex flex-col gap-2">
        <Checkbox checked={never} onChange={handleOnNeverChange}>Never expires</Checkbox>

        <div style={never ? { opacity: 0.4, pointerEvents: 'none' } : undefined}>
          <Calendar disabledDate={disabledDate} fullscreen={false} onSelect={handleOnSelect} value={date} />
        </div>
      </div>
    </FormField>
  );
}

export default VariantD;
