import CodeBlock from '@Components/code-block';
import CodeBlockRawText from '@Components/code-block/raw-text';
import { useFormbitContext } from '@radicalbit/formbit';
import { RbitModal, SectionTitle } from '@radicalbit/radicalbit-design-system';
import { CHAT_CURL } from '../../commands';
import useCurlParams from '../../use-curl-params';
import Actions from './02-actions';
import { ApiKey } from './01-form-fields';

function Modal({ onClose, open }) {
  if (!open) {
    return false;
  }

  return (
    <RbitModal
      actions={<Actions onClose={onClose} />}
      closable
      header={(
        <SectionTitle
          subtitle="Paste the credential you generated in the Credentials section. The request below updates as you type."
          title="Fill credential"
        />
      )}
      onCancel={onClose}
      open
      width={700}
    >
      <div className="flex flex-col gap-4">
        <ApiKey />

        <Preview />
      </div>
    </RbitModal>
  );
}

function Preview() {
  const { projectName, routeName } = useCurlParams();

  const { form } = useFormbitContext();
  const apiKey = form?.apiKey;

  const code = CHAT_CURL(projectName, routeName, apiKey);

  return (
    <CodeBlock code={code}>
      <CodeBlockRawText text={code} />
    </CodeBlock>
  );
}

export default Modal;
