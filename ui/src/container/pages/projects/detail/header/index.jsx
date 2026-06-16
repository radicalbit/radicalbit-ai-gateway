import { DATE_FORMAT, PathsEnum } from '@Src/constants';
import { useGetProjectQuery } from '@State/projects/api';
import { faArrowLeft } from '@fortawesome/free-solid-svg-icons';
import {
  FontAwesomeIcon,
  NewHeader,
  RelativeDateTime,
  SectionTitle,
  Skeleton,
} from '@radicalbit/radicalbit-design-system';
import { useNavigate, useParams } from 'react-router-dom';
import ThreeDotsMenu from './three-dots-menu';

function ProjectDetailHeader() {
  const navigate = useNavigate();
  const { uuid } = useParams();

  const { data, isLoading, isSuccess, isError, error } = useGetProjectQuery(uuid);
  const name = data?.name;

  const handleOnClick = () => {
    const { search } = window.location;
    navigate(`/${PathsEnum.PROJECTS}${search}`);
  };

  if (isLoading) {
    return <IsLoading />;
  }

  if (isError) {
    return <IsError error={error} />;
  }

  if (!isSuccess) {
    return false;
  }

  return (
    <NewHeader
      details={{ one: <ThreeDotsMenu /> }}
      prefix={<FontAwesomeIcon icon={faArrowLeft} onClick={handleOnClick} />}
      title={(
        <SectionTitle
          subtitle={<Subtitle />}
          title={name}
        />
      )}
    />
  );
}

function IsLoading() {
  const navigate = useNavigate();

  const handleOnClick = () => {
    const { search } = window.location;
    navigate(`/${PathsEnum.PROJECTS}${search}`);
  };

  return (
    <NewHeader
      prefix={<FontAwesomeIcon icon={faArrowLeft} onClick={handleOnClick} />}
      title={<Skeleton active block paragraph={0} />}
    />
  );
}

function IsError({ error }) {
  const navigate = useNavigate();
  const status = error?.status;

  const handleOnBack = () => {
    const { search } = window.location;
    navigate(`/${PathsEnum.PROJECTS}${search}`);
  };

  if (status === 404) {
    return (
      <NewHeader
        prefix={<FontAwesomeIcon icon={faArrowLeft} onClick={handleOnBack} />}
        title={(
          <SectionTitle
            subtitle="--"
            title="--"
          />
        )}
      />
    );
  }

  return false;
}

function Subtitle() {
  const { uuid } = useParams();

  const { data } = useGetProjectQuery(uuid);
  const createdAt = data?.createdAt;
  const updatedAt = data?.updatedAt;

  return (
    <div className="flex justify-center gap-1">
      <div>Created</div>

      <RelativeDateTime format={DATE_FORMAT} timestamp={createdAt} withTooltip />

      <div>-</div>

      <div>Updated</div>

      <RelativeDateTime format={DATE_FORMAT} timestamp={updatedAt} withTooltip />
    </div>
  );
}

export default ProjectDetailHeader;
