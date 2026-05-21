import Logo from '@Img/logo.png';
import { PathsEnum } from '@Src/constants';
import { useGetGroupQuery } from '@State/groups/api';
import { Board, Button, Void } from '@radicalbit/radicalbit-design-system';
import { useNavigate, useParams } from 'react-router-dom';
import Keys from './keys';
import Routes from './routes';

function GroupDetail() {
  const { uuid } = useParams();

  const { isError, error, refetch, isSuccess, isLoading } = useGetGroupQuery(uuid);

  if (isError) {
    return <IsError error={error} refetch={refetch} />;
  }

  if (isLoading) {
    return 'Loading...';
  }

  if (!isSuccess) {
    return false;
  }

  return (
    <div className="flex flex-col gap-4">
      <Routes />

      <Keys />
    </div>
  );
}

function IsError({ refetch, error }) {
  const navigate = useNavigate();
  const status = error?.status;

  const handleOnBack = () => {
    const { search } = window.location;
    navigate(`/${PathsEnum.GROUPS}${search}`);
  };

  if (status === 404) {
    return (
      <Board
        main={(
          <Void
            actions={<Button onClick={handleOnBack}>Back</Button>}
            description={(
              <>
                The group do not exist or
                <br />
                might be deleted
              </>
            )}
            image={<img alt="Logo" src={Logo} />}
            title="Group not found"
          />
        )}
        type="secondary"
      />
    );
  }
  return (
    <Board
      main={(
        <Void
          actions={(
            <>
              <Button onClick={handleOnBack}>Back</Button>

              <Button onClick={refetch}>Retry</Button>
            </>
          )}
          description={(
            <>
              This might be temporary
              <br />
              please retry later
            </>
          )}
          image={<img alt="Logo" src={Logo} />}
          title="Unable to load groups"
        />
      )}
    />
  );
}

export default GroupDetail;
