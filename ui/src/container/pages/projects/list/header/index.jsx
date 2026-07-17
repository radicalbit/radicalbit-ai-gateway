import Lucide from '@Components/lucide';
import useModals, { modals } from '@Hooks/use-modals';
import { Button, NewHeader, SectionTitle } from '@radicalbit/radicalbit-design-system';
import { FolderOpen, Plus } from 'lucide-react';

function ProjectsListHeader() {
  return (
    <NewHeader
      details={{
        one: <CreateProjectButton />,
      }}
      title={(
        <SectionTitle
          subtitle="Organize your AI gateway routes by use case. Create a project to get started."
          title="Projects"
          titlePrefix={<Lucide icon={FolderOpen} />}
        />
      )}
    />
  );
}

function CreateProjectButton() {
  const { showModal } = useModals();

  const handleOnClick = () => {
    showModal(modals.CREATE_PROJECT);
  };

  return (
    <Button onClick={handleOnClick} prefix={<Lucide icon={Plus} />} type="primary">
      Create project
    </Button>
  );
}

export default ProjectsListHeader;
export { CreateProjectButton };
