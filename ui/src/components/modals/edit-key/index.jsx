import useAutoFocus from '@Hooks/use-auto-focus';
import useModals from '@Hooks/use-modals';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  Alert,
  Button,
  FormField, Input, RbitModal, SectionTitle, Skeleton, Spinner,
} from '@radicalbit/radicalbit-design-system';
import { useEffect, useRef } from 'react';
import { GATEWAY_OWNER } from '@Src/constants';
import { useGetKeyQuery } from '@State/keys/api';
import { schema } from './schema';
import useHandleOnSubmit from './useHandleOnSubmit';

const DISABLED_CREDENTIALS_TOOLTIP = 'This credential is managed externally and cannot be modified';

function EditKey() {
  return (
    <FormbitContextProvider initialValues={{}} schema={schema}>
      <EditKeyOuter />
    </FormbitContextProvider>
  );
}

function EditKeyOuter() {
  const { hideModal } = useModals();

  return (
    <RbitModal
      actions={<Actions />}
      closable
      header={(
        <SectionTitle
          align="center"
          title="Edit credential"
          titleColor="primary"
        />
      )}
      onCancel={hideModal}
      open
      width={550}
    >
      <Body />
    </RbitModal>
  );
}

function Body() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { error } = useFormbitContext();

  const { data, isLoading: isKeyLoading } = useGetKeyQuery(uuid, { skip: !uuid });
  const isExternallyManaged = data ? data.owner !== GATEWAY_OWNER : false;

  const { isLoading: isInitializing } = useInitializeForm();

  if (isKeyLoading) {
    return <IsLoading />;
  }

  if (isExternallyManaged) {
    return (
      <Alert message={DISABLED_CREDENTIALS_TOOLTIP} type="warning" />
    );
  }

  return (
    <Spinner isFormWrapper spinning={isInitializing}>
      <Name />

      {error('silent.backend') && <FormField message={error('silent.backend')} />}
    </Spinner>
  );
}

function IsLoading() {
  return (
    <Skeleton active block paragraph={{ rows: 1 }} />
  );
}

function Name() {
  const ref = useRef();

  const { error, form, write } = useFormbitContext();
  const name = form?.name;

  const { handleOnSubmit, args: { isLoading } } = useHandleOnSubmit();
  const handleOnChange = ({ target: { value } }) => { write('name', value); };

  useAutoFocus(ref);

  const handleOnPressEnter = () => {
    handleOnSubmit();
  };

  return (
    <FormField
      label="Credential name"
      message={error('name')}
      required
    >
      <Input
        onChange={handleOnChange}
        onPressEnter={handleOnPressEnter}
        readOnly={isLoading}
        ref={ref}
        value={name}
      />
    </FormField>
  );
}

function Actions() {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data, isLoading: isKeyLoading, isSuccess } = useGetKeyQuery(uuid, { skip: !uuid });
  const owner = data?.owner;

  const { handleOnSubmit, args: { isLoading }, isSubmitDisabled } = useHandleOnSubmit();

  if (isKeyLoading) {
    return (
      <>
        <Skeleton.Button active />

        <Skeleton.Button active />
      </>
    );
  }

  if (!isSuccess) {
    return null;
  }

  if (owner !== GATEWAY_OWNER) {
    return null;
  }

  return (
    <>
      <Button onClick={hideModal} type="secondary-light">
        Cancel
      </Button>

      <Button
        disabled={isSubmitDisabled}
        loading={isLoading}
        onClick={handleOnSubmit}
        type="primary"
      >
        Save
      </Button>
    </>
  );
}

const useInitializeForm = () => {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data, ...rest } = useGetKeyQuery(uuid);

  const { initialize } = useFormbitContext();

  useEffect(() => {
    if (data) {
      initialize({ name: data.name });
    }
  }, [initialize, data]);

  return rest;
};

export default EditKey;
