import usePersistProjectUuid from '@Hooks/use-persist-project-uuid';
import { Tabs } from '@radicalbit/radicalbit-design-system';
import { useSearchParams } from 'react-router-dom';
import Consumptions from './consumptions';
import Limits from './limits';

const USAGE_TABS = {
  consumptions: {
    key: 'consumptions',
    label: 'Consumptions',
  },
  limits: {
    key: 'limits',
    label: 'Limits',
  },
};

function Body() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get('usageTab');

  usePersistProjectUuid();

  const handleOnChange = (value) => {
    searchParams.set('usageTab', value);
    setSearchParams(searchParams);
  };

  return (
    <Tabs
      className="custom-tabs"
      defaultActiveKey={tab}
      items={[
        {
          key: USAGE_TABS.consumptions.key,
          label: USAGE_TABS.consumptions.label,
          children: <Consumptions />,
        },
        {
          key: USAGE_TABS.limits.key,
          label: USAGE_TABS.limits.label,
          children: <Limits />,
        },
      ]}
      onChange={handleOnChange}
      sticky
    />
  );
}

export default Body;
