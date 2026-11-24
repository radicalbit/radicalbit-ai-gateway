import Lucide from '@Components/lucide';
import {
  OwnershipTabEnum, TAB_QP, filterByTab, parseTab,
} from '@Helpers/ownership-tabs';
import { useGetGroupsQuery } from '@State/groups/api';
import { Tabs } from '@radicalbit/radicalbit-design-system';
import { ExternalLink, Layers } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';

function OwnershipTabs() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { data = [] } = useGetGroupsQuery();

  const activeKey = parseTab(searchParams.get(TAB_QP));

  const gatewayManagedCount = filterByTab(data, OwnershipTabEnum.GATEWAY_MANAGED).length;
  const externallyManagedCount = filterByTab(data, OwnershipTabEnum.EXTERNALLY_MANAGED).length;

  const items = [
    {
      key: OwnershipTabEnum.GATEWAY_MANAGED,
      label: <TabLabel icon={Layers} text={`Gateway managed (${gatewayManagedCount})`} />,
    },
    {
      key: OwnershipTabEnum.EXTERNALLY_MANAGED,
      label: <TabLabel icon={ExternalLink} text={`Externally managed (${externallyManagedCount})`} />,
    },
  ];

  const handleOnChange = (key) => {
    setSearchParams((prev) => {
      prev.set(TAB_QP, key);
      return prev;
    });
  };

  return <Tabs activeKey={activeKey} items={items} onChange={handleOnChange} />;
}

function TabLabel({ icon, text }) {
  return (
    <span className="flex gap-2 items-center">
      <Lucide icon={icon} size="sm" />

      {text}
    </span>
  );
}

export default OwnershipTabs;
