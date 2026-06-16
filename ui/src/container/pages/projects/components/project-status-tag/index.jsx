import { ProjectStatusEnum } from '@Src/constants';
import { Tag } from '@radicalbit/radicalbit-design-system';

const PROJECT_STATUS_TAG = {
  [ProjectStatusEnum.DEV]: { label: 'Dev', type: 'secondary-light' },
  [ProjectStatusEnum.PROD]: { label: 'Prod', type: 'full' },
};

function ProjectStatusTag({ projectStatus }) {
  const tag = PROJECT_STATUS_TAG[projectStatus];

  if (!tag) {
    return false;
  }

  return <Tag type={tag.type}>{tag.label}</Tag>;
}

export default ProjectStatusTag;
