import usePersistQueryParams from '@Hooks/use-persistence-query-params';
import { Tag } from '@radicalbit/radicalbit-design-system';
import classNames from 'classnames';
import { useSearchParams } from 'react-router-dom';
import './_styles.less';
import CustomRange from './custom-range';
import Presets from './presets';

const defaultKeys = ['from', 'to', 'gte', 'preset'];
export default function TimeFilter({ keys = defaultKeys, reverse = false, storageKey }) {
  const [searchParams] = useSearchParams();
  const isCustom = searchParams.get('preset') === 'custom';

  usePersistQueryParams(keys, storageKey);

  const css = classNames('c-time-filter', { 'c-time-filter--reverse': reverse });

  const customOrPresets = isCustom
    ? <CustomRange />
    : <Presets />;

  return (
    <div className={css}>
      <TimeFilterTag />

      {customOrPresets}
    </div>
  );
}

export function TimeFilterCustomOnly({ keys = defaultKeys, storageKey }) {
  usePersistQueryParams(keys, storageKey);

  return <CustomRange />;
}

function TimeFilterTag() {
  const [searchParams] = useSearchParams();
  const from = searchParams.get('from');
  const to = searchParams.get('to');

  if (!from && !to) {
    return <Tag rounded size="large" type="full">REAL TIME</Tag>;
  }

  if (from && !to) {
    return <Tag rounded size="large" type="full">REAL TIME</Tag>;
  }

  return false;
}
