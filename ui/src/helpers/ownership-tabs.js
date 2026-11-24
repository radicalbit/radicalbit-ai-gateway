import { GATEWAY_OWNER } from '@Src/constants';

const TAB_QP = 'tab';

const OwnershipTabEnum = {
  GATEWAY_MANAGED: 'gateway-managed',
  EXTERNALLY_MANAGED: 'externally-managed',
};

const parseTab = (value) => (value === OwnershipTabEnum.EXTERNALLY_MANAGED ? OwnershipTabEnum.EXTERNALLY_MANAGED : OwnershipTabEnum.GATEWAY_MANAGED);

const isGatewayManaged = ({ owner }) => owner === GATEWAY_OWNER;

const filterByTab = (items, tab) => {
  if (tab === OwnershipTabEnum.EXTERNALLY_MANAGED) {
    return items.filter((item) => !isGatewayManaged(item));
  }

  return items.filter(isGatewayManaged);
};

export {
  OwnershipTabEnum,
  TAB_QP,
  filterByTab,
  parseTab,
};
