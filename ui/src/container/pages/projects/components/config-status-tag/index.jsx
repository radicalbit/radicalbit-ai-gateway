import { ConfigStatusEnum } from '@Src/constants';
import { Tag } from '@radicalbit/radicalbit-design-system';

const CONFIG_STATUS_TAG = {
  [ConfigStatusEnum.DRAFT]: { label: 'Draft', type: 'secondary-light' },
  [ConfigStatusEnum.READY_TO_SERVE]: { label: 'Publish Requested', type: 'warning-light' },
  [ConfigStatusEnum.SERVED]: { label: 'Published in Prod', type: 'full' },
};

function ConfigStatusTag({ configStatus }) {
  const tag = CONFIG_STATUS_TAG[configStatus];

  if (!tag) {
    return false;
  }

  return <Tag type={tag.type}>{tag.label}</Tag>;
}

export default ConfigStatusTag;
