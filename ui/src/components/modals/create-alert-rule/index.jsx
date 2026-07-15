import useModals from '@Hooks/use-modals';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  RbitModal, SectionTitle, Spinner,
} from '@radicalbit/radicalbit-design-system';
import { schema } from './schema';
import StepA from './step-a';
import StepB from './step-b';
import StepC from './step-c';

const INITIAL_VALUES = { recipients: [], enabled: false, __metadata: { step: 0 } };

const STEP_SUBTITLES = [
  'Step 1 - Name rule',
  'Step 2 - Rule setup',
  'Step 3 - Channel and activation',
];

const STEP_COMPONENTS = [<StepA />, <StepB />, <StepC />];

function CreateAlertRule() {
  return (
    <FormbitContextProvider initialValues={INITIAL_VALUES} schema={schema}>
      <CreateAlertRuleInner />
    </FormbitContextProvider>
  );
}

function CreateAlertRuleInner() {
  const { hideModal } = useModals();
  const { form } = useFormbitContext();
  const step = form?.__metadata?.step ?? 0;

  const stepComponent = STEP_COMPONENTS[step];
  const subtitle = STEP_SUBTITLES[step];

  return (
    <RbitModal
      closable
      header={(
        <SectionTitle
          subtitle={subtitle}
          title="Create Alert"
          titleColor="primary"
        />
      )}
      onCancel={hideModal}
      open
      width={550}
    >
      <Spinner isFormWrapper>
        {stepComponent}
      </Spinner>
    </RbitModal>
  );
}

export default CreateAlertRule;
