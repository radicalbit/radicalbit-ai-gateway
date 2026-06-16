import { ConfigStatusEnum } from '@Src/constants';
import useGetActiveConfig from '../useGetActiveConfig';
import ChatbotDraft from './chatbot-draft';
import ChatbotReadyToServe from './chatbot-ready-to-serve';
import ChatbotServed from './chatbot-served';

function Chatbot() {
  const { activeConfig, projectUuid } = useGetActiveConfig();

  if (!activeConfig) {
    return false;
  }

  switch (activeConfig.configStatus) {
    case ConfigStatusEnum.READY_TO_SERVE:
      return <ChatbotReadyToServe />;

    case ConfigStatusEnum.SERVED:
      return <ChatbotServed />;

    case ConfigStatusEnum.DRAFT:
    default:
      return <ChatbotDraft config={activeConfig} projectUuid={projectUuid} />;
  }
}

export default Chatbot;
