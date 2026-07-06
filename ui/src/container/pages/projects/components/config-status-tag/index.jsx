import { ConfigStatusEnum } from '@Src/constants';
import { Tag } from '@radicalbit/radicalbit-design-system';

const CONFIG_STATUS_TAG = {
  [ConfigStatusEnum.EMPTY]: { label: 'Empty', type: 'secondary-light' },
  [ConfigStatusEnum.DRAFT]: { label: 'Draft', type: 'secondary' },
  [ConfigStatusEnum.READY_TO_SERVE]: { label: 'Publish Requested', type: 'warning-light' },
  [ConfigStatusEnum.SERVED]: { label: 'Published in Prod', type: 'full' },
};

function ConfigStatusTag({ config }) {
  const configStatus = config?.configStatus;
  const updatedAt = config?.updatedAt;

  const tag = !updatedAt ? CONFIG_STATUS_TAG[ConfigStatusEnum.EMPTY] : CONFIG_STATUS_TAG[configStatus];

  if (!tag) {
    return false;
  }

  return <Tag type={tag.type}>{tag.label}</Tag>;
}

export default ConfigStatusTag;
