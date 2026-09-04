import CodeBlock from '@Components/code-block';
import CodeBlockRawText from '@Components/code-block/raw-text';
import { useFormbitContext } from '@radicalbit/formbit';
import { RbitModal, SectionTitle } from '@radicalbit/radicalbit-design-system';
import { TRANSCRIPTION_CURL } from '../../commands';
import useCurlParams from '../../use-curl-params';
import { ApiKey, AudioPath } from './01-form-fields';
import Actions from './02-actions';

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
          subtitle="Paste your credential and the absolute path of the audio file to transcribe. The request below updates as you type."
          title="Fill parameters"
        />
      )}
      onCancel={onClose}
      open
      width={700}
    >
      <div className="flex flex-col gap-4">
        <ApiKey />

        <AudioPath />

        <Preview />
      </div>
    </RbitModal>
  );
}

function Preview() {
  const { projectName, routeName } = useCurlParams();

  const { form } = useFormbitContext();
  const apiKey = form?.apiKey;
  const audioPath = form?.audioPath;

  const code = TRANSCRIPTION_CURL(projectName, routeName, apiKey, audioPath);

  return (
    <CodeBlock code={code}>
      <CodeBlockRawText text={code} />
    </CodeBlock>
  );
}

export default Modal;
