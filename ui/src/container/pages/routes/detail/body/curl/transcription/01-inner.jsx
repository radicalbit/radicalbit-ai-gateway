import CodeBlock from '@Components/code-block';
import CodeBlockRawText from '@Components/code-block/raw-text';
import Lucide from '@Components/lucide';
import { useGetRouteByNameWithRange } from '@State/routes/vertical-hooks';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Board, Button, FormField, SectionTitle,
} from '@radicalbit/radicalbit-design-system';
import { SlidersHorizontal } from 'lucide-react';
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { TRANSCRIPTION_CURL } from '../commands';
import useCurlParams from '../use-curl-params';
import Modal from './modal';

function Inner() {
  const { name } = useParams();

  const { data: route } = useGetRouteByNameWithRange(name);
  const transcriptionModels = route?.configuration?.transcriptionModels;

  if (!transcriptionModels?.length) {
    return false;
  }

  return (
    <Board
      borderType="none"
      header={<SectionTitle size="small" title="Transcription model cURL" />}
      main={<Content />}
      size="small"
    />
  );
}

function Content() {
  const [isModalOpen, setIsModalOpen] = useState(false);

  const { projectName, routeName } = useCurlParams();

  const { form } = useFormbitContext();
  const apiKey = form?.apiKey;
  const audioPath = form?.audioPath;

  const code = TRANSCRIPTION_CURL(projectName, routeName, apiKey, audioPath);

  const handleOnOpenModal = () => { setIsModalOpen(true); };
  const handleOnCloseModal = () => { setIsModalOpen(false); };

  return (
    <>
      <CodeBlock
        actions={(
          <Button onClick={handleOnOpenModal} type="secondary">
            <Lucide icon={SlidersHorizontal} />

            <div>Fill parameters</div>
          </Button>
        )}
        code={code}
        hasCopyToClipboard
      >
        <CodeBlockRawText text={code} />
      </CodeBlock>

      <BoardError />

      <Modal onClose={handleOnCloseModal} open={isModalOpen} />
    </>
  );
}

function BoardError() {
  const { error } = useFormbitContext();
  const message = error('apiKey') || error('audioPath');

  if (!message) {
    return false;
  }

  return <FormField message={message} />;
}

export default Inner;
