import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import useModals from '@Hooks/use-modals';
import { useGetProjectQuery } from '@State/projects/api';
import { faArrowLeft, faFolderOpen } from '@fortawesome/free-solid-svg-icons';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  FontAwesomeIcon,
  NewHeader, RbitModal, SectionTitle, Skeleton,
} from '@radicalbit/radicalbit-design-system';
import { useEffect } from 'react';
import Chatbot from './chatbot';
import CodeEditor from './code-editor';
import { schema } from './schema';

function EditProjectConfig() {
  return (
    <FormbitContextProvider initialValues={{ configs: {} }} schema={schema}>
      <EditProjectConfigOuter />
    </FormbitContextProvider>
  );
}

function EditProjectConfigOuter() {
  const { hideModal } = useModals();

  return (
    <RbitModal
      closable={false}
      defaultMaximize
      header={<Header />}
      onCancel={hideModal}
      open
    >
      <Body />
    </RbitModal>
  );
}

function Header() {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data: project, isLoading } = useGetProjectQuery(uuid, { skip: !uuid });

  const title = project?.name ?? '';
  const subtitle = project?.description || '--';

  if (isLoading) {
    return (
      <NewHeader
        prefix={<FontAwesomeIcon icon={faArrowLeft} onClick={hideModal} />}
        title={<Skeleton.Input active />}
      />
    );
  }

  return (
    <NewHeader
      prefix={<FontAwesomeIcon icon={faArrowLeft} onClick={hideModal} />}
      title={<SectionTitle subtitle={subtitle} title={title} titlePrefix={<FontAwesomeIcon icon={faFolderOpen} />} />}
    />
  );
}

function Body() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { isLoading, isError, isSuccess } = useGetProjectQuery(uuid, { skip: !uuid });
  const { isLoading: isInitializing } = useInitializeForm();

  if (isLoading || isInitializing) {
    return <Skeleton active block paragraph={{ rows: 8 }} />;
  }

  if (isError) {
    return <SomethingWentWrong />;
  }

  if (!isSuccess) {
    return false;
  }

  return (
    <div className="flex flex-col h-full gap-2">
      <div className="grid grid-cols-2 gap-4 flex-1 min-h-0">
        <CodeEditor />

        <Chatbot />
      </div>
    </div>
  );
}

const useInitializeForm = () => {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data, ...rest } = useGetProjectQuery(uuid, { skip: !uuid });

  const { initialize } = useFormbitContext();

  useEffect(() => {
    if (data) {
      const configs = (data.configs ?? []).reduce(
        (acc, config) => ({ ...acc, [config.uuid]: config.configFile ?? '' }),
        {},
      );

      initialize({ configs });
    }
  }, [initialize, data]);

  return rest;
};

export default EditProjectConfig;
