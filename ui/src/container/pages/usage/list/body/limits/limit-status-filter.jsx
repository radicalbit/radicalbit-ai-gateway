import { Select } from '@radicalbit/radicalbit-design-system';
import { useSearchParams } from 'react-router-dom';
import { parseWindowStatuses } from './helpers';

const OPTIONS = [
  { label: 'Normal (0-70%)', tagLabel: 'Normal', value: 'ok' },
  { label: 'Warning (71-90%)', tagLabel: 'Warning', value: 'warning' },
  { label: 'Critical (91-100%)', tagLabel: 'Critical', value: 'critical' },
];

function LimitStatusFilter({ id }) {
  const [searchParams, setSearchParams] = useSearchParams();

  const selectedStatuses = parseWindowStatuses(searchParams.get('windowStatuses'));

  const handleOnChange = (values) => {
    setSearchParams((prev) => {
      if (values.length === 0) {
        prev.delete('windowStatuses');
      } else {
        prev.set('windowStatuses', values.join(','));
      }
      return prev;
    });
  };

  return (
    <Select
      allowClear
      id={id}
      minWidth={240}
      mode="multiple"
      onChange={handleOnChange}
      optionLabelProp="tagLabel"
      options={OPTIONS}
      placeholder="Please select"
      value={selectedStatuses}
    />
  );
}

export default LimitStatusFilter;
