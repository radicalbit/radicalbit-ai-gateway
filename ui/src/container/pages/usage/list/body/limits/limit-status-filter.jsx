import { Select } from '@radicalbit/radicalbit-design-system';
import { useSearchParams } from 'react-router-dom';

const OPTIONS = [
  { label: 'Normal (0-70%)', value: 'ok' },
  { label: 'Warning (71-90%)', value: 'warning' },
  { label: 'Critical (91-100%)', value: 'critical' },
];

function LimitStatusFilter() {
  const [searchParams, setSearchParams] = useSearchParams();

  const selectedStatuses = searchParams.get('windowStatuses')
    ? searchParams.get('windowStatuses').split(',')
    : [];

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
      maxTagCount="responsive"
      mode="multiple"
      onChange={handleOnChange}
      options={OPTIONS}
      placeholder="Please select"
      style={{ width: 400 }}
      value={selectedStatuses}
    />
  );
}

export default LimitStatusFilter;
