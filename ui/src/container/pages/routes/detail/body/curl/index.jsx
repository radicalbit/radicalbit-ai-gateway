import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import { useGetProjectQuery } from '@State/projects/api';
import { useGetRouteByNameWithRange } from '@State/routes/vertical-hooks';
import { Board, Skeleton, Void } from '@radicalbit/radicalbit-design-system';
import { useParams, useSearchParams } from 'react-router-dom';
import ChatCurl from './chat';
import TranscriptionCurl from './transcription';

function Curl() {
  const { name } = useParams();

  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const { isLoading, isError, isSuccess } = useGetProjectQuery(projectUuid, { skip: !projectUuid });
  const { data: route,
    isLoading: isRouteLoading,
    isError: isRouteError,
    isSuccess: isRouteSuccess } = useGetRouteByNameWithRange(name);
  const chatModels = route?.configuration?.chatModels;
  const transcriptionModels = route?.configuration?.transcriptionModels;

  if (isLoading || isRouteLoading) {
    return <Skeleton.Input active block />;
  }

  if (isError || isRouteError) {
    return <SomethingWentWrong />;
  }

  if (!chatModels?.length && !transcriptionModels?.length) {
    return <IsEmpty />;
  }

  if (!isSuccess || !isRouteSuccess) {
    return false;
  }

  return (
    <div className="flex flex-col gap-4">
      <ChatCurl />

      <TranscriptionCurl />
    </div>
  );
}

function IsEmpty() {
  return (
    <Board
      main={(
        <Void
          description="This route has no models configured yet. cURL examples appear once you add a chat or transcription model."
          size="small"
          title="No cURL available"
        />
      )}
      size="small"
    />
  );
}

export default Curl;
