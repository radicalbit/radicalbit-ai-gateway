import { Select } from '@radicalbit/radicalbit-design-system';
import { useSearchParams } from 'react-router-dom';
import dayjs from 'dayjs';
import localeData from 'dayjs/plugin/localeData';
import weekday from 'dayjs/plugin/weekday';

dayjs.extend(weekday);
dayjs.extend(localeData);

const presets = [
  { label: 'Last hour', seconds: 3600 },
  { label: 'Last 12 hours', seconds: 3600 * 12 },
  { label: 'Last day', seconds: 3600 * 24 },
  { label: 'Last 2 days', seconds: 3600 * 24 * 2 },
];

function Presets() {
  const [searchParams, setSearchParams] = useSearchParams();
  const curr = searchParams.get('preset');

  const handleSelectChange = (value) => {
    // allowClear
    if (!value) {
      searchParams.delete('from');
      searchParams.delete('to');
      searchParams.delete('gte');
      searchParams.delete('preset');
      setSearchParams(searchParams, { replace: true });
    }

    if (value === 'custom-range') {
      // Switch to custom range mode and clear query params related to preset/range
      searchParams.delete('from');
      searchParams.delete('to');
      searchParams.set('preset', 'custom');
      setSearchParams(searchParams, { replace: true });
      return;
    }

    // Find preset seconds
    const preset = presets.find((p) => p.label === value);
    if (!preset) return;

    searchParams.set('gte', preset.seconds);
    searchParams.set('preset', preset.label);
    setSearchParams(searchParams, { replace: true });
  };

  return (
    <Select
      allowClear
      onChange={handleSelectChange}
      options={[
        ...presets.map((p) => ({ label: p.label, value: p.label })),
        { label: 'Custom Range', value: 'custom-range' },
      ]}
      placeholder="Select Time Range"
      showSearch={false}
      style={{ width: 200 }}
      value={curr}
    />
  );
}

export default Presets;
