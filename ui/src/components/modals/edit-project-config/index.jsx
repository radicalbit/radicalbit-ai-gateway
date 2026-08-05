import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import Lucide from '@Components/lucide';
import { notificationErrorJson } from '@Helpers/notificationUtils';
import useModals from '@Hooks/use-modals';
import { ConfigStatusEnum } from '@Src/constants';
import { actions as notificationActions } from '@State/notification';
import { useGetProjectQuery, useImportConfigMutation, useLazyExportAllConfigsQuery, useLazyExportConfigQuery } from '@State/projects/api';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  Button,
  Dropdown,
  NewHeader, RbitModal, SectionTitle, Skeleton,
  Upload,
} from '@radicalbit/radicalbit-design-system';
import {
  ArrowLeft, FileDown, FileUp, FolderOpen,
} from 'lucide-react';
import { useEffect } from 'react';
import { useDispatch } from 'react-redux';
import Chatbot from './chatbot';
import CodeEditor from './code-editor';
import { schema } from './schema';
import useGetActiveConfig from './useGetActiveConfig';

const ACCEPTED_IMPORT_EXTENSIONS = '.yaml,.yml';
const PREVENT_AUTO_UPLOAD = Upload.LIST_IGNORE ?? false;

const hasYamlExtension = (name = '') => /\.(yaml|yml)$/i.test(name);

const triggerBrowserDownload = ({ blob, filename }) => {
  const objectUrl = window.URL.createObjectURL(blob);
  const anchor = window.document.createElement('a');

  anchor.href = objectUrl;
  anchor.download = filename;
  window.document.body.appendChild(anchor);
  anchor.click();
  window.document.body.removeChild(anchor);
  window.URL.revokeObjectURL(objectUrl);
};

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
      backgroundLevel={0}
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
        prefix={<Lucide icon={ArrowLeft} onClick={hideModal} />}
        title={<Skeleton.Input active />}
      />
    );
  }

  return (
    <NewHeader
      details={
        {
          one: <ImportButton />,
          two: <ExportButton />,
        }
      }
      prefix={<Lucide icon={ArrowLeft} onClick={hideModal} />}
      title={<SectionTitle subtitle={subtitle} title={title} titlePrefix={<Lucide icon={FolderOpen} />} />}
    />
  );
}

function ImportButton() {
  const dispatch = useDispatch();
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { activeConfig } = useGetActiveConfig();
  const configUuid = activeConfig?.uuid;
  const isNotDraft = activeConfig?.configStatus !== ConfigStatusEnum.DRAFT;

  const [trigger, { isLoading }] = useImportConfigMutation({ fixedCacheKey: `import-config-${uuid}` });

  const isDisabled = isLoading || isNotDraft;

  const notifyError = (content) => {
    dispatch(notificationActions.setNotificationMessage(notificationErrorJson({ message: content })));
  };

  const handleBeforeUpload = (file) => {
    if (!hasYamlExtension(file.name)) {
      notifyError('Only YAML files (.yaml, .yml) are allowed.');
      return PREVENT_AUTO_UPLOAD;
    }

    if (file.size === 0) {
      notifyError('The selected file is empty.');
      return PREVENT_AUTO_UPLOAD;
    }

    const data = new FormData();
    data.append('file', file);

    trigger({
      projectUuid: uuid,
      configUuid,
      data,
      successMessage: `Import ${file.name} file success`,
    });

    return PREVENT_AUTO_UPLOAD;
  };

  return (
    <Upload
      accept={ACCEPTED_IMPORT_EXTENSIONS}
      beforeUpload={handleBeforeUpload}
      disabled={isDisabled}
      showUploadList={false}
    >
      <Button disabled={isDisabled} icon={<Lucide icon={FileDown} />} loading={isLoading} onClick={() => {}} type="primary-outlined">
        Import
      </Button>
    </Upload>
  );
}

function ExportButton() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { activeConfig } = useGetActiveConfig();
  const configUuid = activeConfig?.uuid;
  const slot = activeConfig?.slot;

  const [triggerExportAll, { isLoading: isLoadingAll }] = useLazyExportAllConfigsQuery();
  const [triggerExport, { isLoading }] = useLazyExportConfigQuery();

  const isExporting = isLoading || isLoadingAll;

  const handleOnExportCurrent = async () => {
    if (isExporting || !configUuid) {
      return;
    }

    const result = await triggerExport({ projectUuid: uuid, configUuid });

    if (result.data) {
      triggerBrowserDownload(result.data);
    }
  };

  const handleOnExportAll = async () => {
    if (isExporting) {
      return;
    }

    const result = await triggerExportAll({ projectUuid: uuid });

    if (result.data) {
      triggerBrowserDownload(result.data);
    }
  };

  const items = [
    {
      key: 'export-current',
      label: `Export Slot ${slot}`,
      onClick: handleOnExportCurrent,
    },
    {
      key: 'export-all',
      label: 'Export all slots',
      onClick: handleOnExportAll,
    },
  ];

  return (
    <Dropdown menu={{ items }} trigger={['hover']}>
      <Button icon={<Lucide icon={FileUp} />} loading={isExporting} type="primary-outlined">
        Export
      </Button>
    </Dropdown>
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
