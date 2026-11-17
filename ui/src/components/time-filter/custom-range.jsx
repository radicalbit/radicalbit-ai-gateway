import { RangePicker } from '@radicalbit/radicalbit-design-system';
import dayjs from 'dayjs';
import localeData from 'dayjs/plugin/localeData';
import weekday from 'dayjs/plugin/weekday';
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

dayjs.extend(weekday);
dayjs.extend(localeData);

function CustomRange({ id }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const rangeValue = useGetRangeValue();

  const handleRangeChange = (dates) => {
    // support the allowClear if present
    if (!dates || dates.length !== 2) {
      searchParams.delete('from');
      searchParams.delete('to');
      searchParams.delete('preset');
      searchParams.delete('gte');
      setSearchParams(searchParams, { replace: true });

      return;
    }

    const [start, end] = dates;
    searchParams.set('from', start.unix());
    searchParams.set('to', end.unix());
    searchParams.delete('gte');
    setSearchParams(searchParams, { replace: true });
  };

  return (
    <RangePicker
      allowClear
      format="YYYY-MMM-DD HH:mm"
      id={id}
      onChange={handleRangeChange}
      placeholder={['Start date (no limit)', 'End date (no limit)']}
      showTime
      style={{ width: 360 }}
      value={rangeValue}
    />
  );
}

const useGetRangeValue = () => {
  const [searchParams] = useSearchParams();
  const from = searchParams.get('from');
  const to = searchParams.get('to');

  return useMemo(() => {
    if (from && to) {
      const fromDayjs = dayjs.unix(Number(from));
      const toDayjs = dayjs.unix(Number(to));

      if (fromDayjs.isValid() && toDayjs.isValid()) {
        return [fromDayjs, toDayjs];
      }
    }

    return undefined;
  }, [from, to]);
};

export default CustomRange;
