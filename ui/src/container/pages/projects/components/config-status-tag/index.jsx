import { ConfigStatusEnum } from '@Src/constants';
import { Tag } from '@radicalbit/radicalbit-design-system';

const CONFIG_STATUS_TAG = {
  [ConfigStatusEnum.READY_TO_SERVE]: { label: 'Publish Requested', type: 'warning-outlined' },
  [ConfigStatusEnum.SERVED]: { label: 'Published in Prod', type: 'success-outlined' },
};

function ConfigStatusTag({ config }) {
  const configStatus = config?.configStatus;
  const updatedAt = config?.updatedAt;

  const tag = !updatedAt ? CONFIG_STATUS_TAG[ConfigStatusEnum.EMPTY] : CONFIG_STATUS_TAG[configStatus];

  if (!tag) {
    return false;
  }

  return <Tag rounded size="large" type={tag.type}>{tag.label}</Tag>;
}

export default ConfigStatusTag;
