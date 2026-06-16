import useModals, { modals } from '@Hooks/use-modals';
import { faFolderOpen, faPlus } from '@fortawesome/free-solid-svg-icons';
import { Button, FontAwesomeIcon, NewHeader, SectionTitle } from '@radicalbit/radicalbit-design-system';

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
          titlePrefix={<FontAwesomeIcon icon={faFolderOpen} />}
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
    <Button onClick={handleOnClick} prefix={<FontAwesomeIcon icon={faPlus} />} type="primary">
      Create project
    </Button>
  );
}

export default ProjectsListHeader;
export { CreateProjectButton };
