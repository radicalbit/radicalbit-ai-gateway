import { PathsEnum } from '@Src/constants';
import { useGetRouteByNameWithRange } from '@Src/store/state/routes/vertical-hooks';
import { faArrowLeft } from '@fortawesome/free-solid-svg-icons';
import {
  CopyToClipboard,
  FontAwesomeIcon, NewHeader,
  SectionTitle,
  Skeleton,
} from '@radicalbit/radicalbit-design-system';
import { useNavigate, useParams } from 'react-router-dom';
import ThreeDotsMenu from './three-dots-menu';

function RouteDetailHeader() {
  const navigate = useNavigate();
  const { name } = useParams();

  const { data, isLoading, isError, isSuccess } = useGetRouteByNameWithRange(name);
  const routeName = data?.routeName;

  const handleOnClick = () => {
    const { search } = window.location;
    navigate(`/${PathsEnum.ROUTES}${search}`);
  };

  if (isLoading) {
    return <IsLoading />;
  }

  if (isError) {
    return (
      <NewHeader
        prefix={<FontAwesomeIcon icon={faArrowLeft} onClick={handleOnClick} />}
      />
    );
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
          icon={<CopyToClipboard link={routeName} tooltip={{ mouseEnterDelay: 0 }} />}
          subtitle="View route setup"
          title={routeName}
        />
      )}
    />
  );
}

function IsLoading() {
  const navigate = useNavigate();

  const handleOnClick = () => {
    const { search } = window.location;
    navigate(`/${PathsEnum.ROUTES}${search}`);
  };

  return (
    <NewHeader
      prefix={<FontAwesomeIcon icon={faArrowLeft} onClick={handleOnClick} />}
      title={<Skeleton active block paragraph={0} />}
    />
  );
}

export default RouteDetailHeader;
