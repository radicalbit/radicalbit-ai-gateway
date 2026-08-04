import useModals from '@Hooks/use-modals';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  RbitModal, SectionTitle, Spinner,
} from '@radicalbit/radicalbit-design-system';
import { schema } from './schema';
import StepA from './step-a';
import StepAActions from './step-a/actions';
import StepB from './step-b';
import StepBActions from './step-b/actions';
import StepC from './step-c';
import StepCActions from './step-c/actions';

const INITIAL_VALUES = { recipients: [], enabled: false, __metadata: { step: 0 } };

const STEP_SUBTITLES = [
  'Step 1 - Name rule',
  'Step 2 - Rule setup',
  'Step 3 - Channel and activation',
];

const STEP_COMPONENTS = [<StepA />, <StepB />, <StepC />];

const STEP_ACTIONS = [<StepAActions />, <StepBActions />, <StepCActions />];

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
  const stepActions = STEP_ACTIONS[step];
  const subtitle = STEP_SUBTITLES[step];

  return (
    <RbitModal
      actions={stepActions}
      closable
      header={(
        <SectionTitle
          subtitle={subtitle}
          title="Create Alert"
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
