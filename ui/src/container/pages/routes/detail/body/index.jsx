import { Tabs } from '@radicalbit/radicalbit-design-system';
import { useSearchParams } from 'react-router-dom';
import AssociatedGroups from './associated-groups';
import Configurations from './configurations';
import Curl from './curl';
import Events from './events';
import Prompts from './prompts';

export const ROUTE_DETAIL_TABS = {
  events: {
    key: 'events',
    label: 'Events',
  },
  configurations: {
    key: 'configurations',
    label: 'Configurations',
  },
  associations: {
    key: 'associations',
    label: 'Associations',
  },
  curl: {
    key: 'curl',
    label: 'cURL',
  },
  prompts: {
    key: 'prompts',
    label: 'Prompts',
  },
};

const items = [
  {
    key: ROUTE_DETAIL_TABS.events.key,
    label: ROUTE_DETAIL_TABS.events.label,
    children: <Events />,
  },
  {
    key: ROUTE_DETAIL_TABS.configurations.key,
    label: ROUTE_DETAIL_TABS.configurations.label,
    children: <Configurations />,
  },
  {
    key: ROUTE_DETAIL_TABS.prompts.key,
    label: ROUTE_DETAIL_TABS.prompts.label,
    children: <Prompts />,
  },
  {
    key: ROUTE_DETAIL_TABS.associations.key,
    label: ROUTE_DETAIL_TABS.associations.label,
    children: <AssociatedGroups />,
  },
  {
    key: ROUTE_DETAIL_TABS.curl.key,
    label: ROUTE_DETAIL_TABS.curl.label,
    children: <Curl />,
  },
];

function RouteDetail() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeKey = searchParams.get('tab') ?? 'events';

  const onChange = (key) => {
    searchParams.set('tab', key);
    setSearchParams(searchParams);
  };

  return (
    <Tabs activeKey={activeKey} items={items} onChange={onChange} />
  );
}

export default RouteDetail;
