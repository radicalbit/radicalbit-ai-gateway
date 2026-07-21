import Lucide from '@Components/lucide';
import { DATE_FORMAT, PathsEnum } from '@Src/constants';
import { useGetGroupQuery } from '@State/groups/api';
import {
  NewHeader,
  RelativeDateTime, SectionTitle, Skeleton,
} from '@radicalbit/radicalbit-design-system';
import { ArrowLeft } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import ThreeDotsMenu from './three-dots-menu';

function GroupDetailHeader() {
  const navigate = useNavigate();
  const { uuid } = useParams();

  const { data, isLoading, isSuccess, isError, error } = useGetGroupQuery(uuid);
  const name = data?.name;

  const handleOnClick = () => {
    const { search } = window.location;
    navigate(`/${PathsEnum.GROUPS}${search}`);
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
      prefix={<Lucide icon={ArrowLeft} onClick={handleOnClick} />}
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
  return (
    <NewHeader
      title={<Skeleton active paragraph={{ rows: 1 }} title={false} />}
    />
  );
}

function IsError({ error }) {
  const navigate = useNavigate();
  const status = error?.status;

  const handleOnBack = () => {
    const { search } = window.location;
    navigate(`/${PathsEnum.GROUPS}${search}`);
  };

  if (status === 404) {
    return (
      <NewHeader
        prefix={<Lucide icon={ArrowLeft} onClick={handleOnBack} />}
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

  const { data } = useGetGroupQuery(uuid);
  const createdAt = data?.createdAt;
  const updatedAt = data?.updatedAt;

  return (
    <div className="flex justify-center gap-1">
      <div>
        Created
      </div>

      <RelativeDateTime format={DATE_FORMAT} timestamp={createdAt} />

      <div>-</div>

      <div>
        Updated
      </div>

      <RelativeDateTime format={DATE_FORMAT} timestamp={updatedAt} />
    </div>
  );
}

export default GroupDetailHeader;
