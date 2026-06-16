import Logo from '@Img/logo.png';
import { PathsEnum } from '@Src/constants';
import { useGetProjectQuery } from '@State/projects/api';
import { Board, Button, Skeleton, Void } from '@radicalbit/radicalbit-design-system';
import { useNavigate, useParams } from 'react-router-dom';

function ProjectDetail() {
  const { uuid } = useParams();

  const { isError, error, refetch, isSuccess, isLoading } = useGetProjectQuery(uuid);

  if (isError) {
    return <IsError error={error} refetch={refetch} />;
  }

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton.Input active block style={{ height: 200, borderRadius: 8 }} />
      </div>
    );
  }

  if (!isSuccess) {
    return false;
  }

  return <div className="flex flex-col gap-4" />;
}

function IsError({ refetch, error }) {
  const navigate = useNavigate();
  const status = error?.status;

  const handleOnBack = () => {
    const { search } = window.location;
    navigate(`/${PathsEnum.PROJECTS}${search}`);
  };

  if (status === 404) {
    return (
      <Board
        main={(
          <Void
            actions={<Button onClick={handleOnBack}>Back</Button>}
            description={(
              <>
                The project does not exist or
                <br />
                might be deleted
              </>
            )}
            image={<img alt="Logo" src={Logo} />}
            title="Project not found"
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
          title="Unable to load project"
        />
      )}
    />
  );
}

export default ProjectDetail;
