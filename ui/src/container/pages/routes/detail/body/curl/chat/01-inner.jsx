import CodeBlock from '@Components/code-block';
import CodeBlockRawText from '@Components/code-block/raw-text';
import Lucide from '@Components/lucide';
import { useGetRouteByNameWithRange } from '@State/routes/vertical-hooks';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Board, Button, FormField, SectionTitle,
} from '@radicalbit/radicalbit-design-system';
import { KeyRound } from 'lucide-react';
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { CHAT_CURL } from '../commands';
import useCurlParams from '../use-curl-params';
import Modal from './modal';

function Inner() {
  const { name } = useParams();

  const { data: route } = useGetRouteByNameWithRange(name);
  const chatModels = route?.configuration?.chatModels;

  if (!chatModels?.length) {
    return false;
  }

  return (
    <Board
      borderType="none"
      header={<SectionTitle size="small" title="Chat model cURL" />}
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

  const code = CHAT_CURL(projectName, routeName, apiKey);

  const handleOnOpenModal = () => { setIsModalOpen(true); };
  const handleOnCloseModal = () => { setIsModalOpen(false); };

  return (
    <>
      <CodeBlock
        actions={(
          <Button onClick={handleOnOpenModal} type="secondary">
            <Lucide icon={KeyRound} />

            <div>Fill credential</div>
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
  const message = error('apiKey');

  if (!message) {
    return false;
  }

  return <FormField message={message} />;
}

export default Inner;
