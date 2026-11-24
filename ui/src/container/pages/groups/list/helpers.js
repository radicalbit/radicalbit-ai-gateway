import { GATEWAY_OWNER } from '@Src/constants';

const TAB_QP = 'tab';

const GroupsTabEnum = {
  GATEWAY_MANAGED: 'gateway-managed',
  EXTERNALLY_MANAGED: 'externally-managed',
};

const parseTab = (value) => (value === GroupsTabEnum.EXTERNALLY_MANAGED ? GroupsTabEnum.EXTERNALLY_MANAGED : GroupsTabEnum.GATEWAY_MANAGED);

const isGatewayManaged = ({ owner }) => owner === GATEWAY_OWNER;

const filterByTab = (groups, tab) => {
  if (tab === GroupsTabEnum.EXTERNALLY_MANAGED) {
    return groups.filter((group) => !isGatewayManaged(group));
  }

  return groups.filter(isGatewayManaged);
};

const filterByName = (groups, searchValue) => {
  if (!searchValue) {
    return groups;
  }

  return groups.filter(({ name }) => name.toLowerCase().includes(searchValue.toLowerCase()));
};

export {
  GroupsTabEnum,
  TAB_QP,
  filterByName,
  filterByTab,
  parseTab,
};
