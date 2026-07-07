import useModals, { modals } from '@Hooks/use-modals';
import { useGetProjectQuery } from '@State/projects/api';

const useGetActiveConfig = () => {
  const { showModal, modalPayload } = useModals();
  const projectUuid = modalPayload?.data?.uuid;
  const activeConfigUuid = modalPayload?.data?.activeConfigUuid;

  const { data: project } = useGetProjectQuery(projectUuid, { skip: !projectUuid });
  const configs = project?.configs ?? [];

  const activeConfig = configs.find((c) => c.uuid === activeConfigUuid) ?? configs[0];

  const selectConfig = (uuid) => {
    showModal(modals.EDIT_PROJECT_CONFIG, { uuid: projectUuid, activeConfigUuid: uuid });
  };

  return {
    activeConfig,
    configs,
    projectUuid,
    selectConfig,
  };
};

export default useGetActiveConfig;
