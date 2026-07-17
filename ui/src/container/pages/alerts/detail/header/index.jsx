import Lucide from '@Components/lucide';
import { PathsEnum } from '@Src/constants';
import { useGetAlertQuery, useToggleAlertMutation } from '@State/alerts/api';
import {
  NewHeader, SectionTitle, Skeleton, Switch,
} from '@radicalbit/radicalbit-design-system';
import { ArrowLeft } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';

function AlertDetailHeader() {
  const navigate = useNavigate();
  const { uuid } = useParams();

  const { data, isLoading, isSuccess, isError, error } = useGetAlertQuery(uuid);
  const name = data?.name;
  const description = data?.description;

  const handleOnBack = () => {
    const { search } = window.location;
    navigate(`/${PathsEnum.ALERTS}${search}`);
  };

  if (isLoading) {
    return <IsLoading />;
  }

  if (isError) {
    return <IsError error={error} onBack={handleOnBack} />;
  }

  if (!isSuccess) {
    return false;
  }

  return (
    <NewHeader
      details={{ one: <EnabledToggle /> }}
      prefix={<Lucide icon={ArrowLeft} onClick={handleOnBack} />}
      title={(
        <SectionTitle
          subtitle={description ?? '--'}
          title={name}
        />
      )}
    />
  );
}

function EnabledToggle() {
  const { uuid } = useParams();
  const { data } = useGetAlertQuery(uuid);
  const enabled = data?.enabled ?? false;

  const [trigger, { isLoading }] = useToggleAlertMutation({ fixedCacheKey: `toggle-alert-${uuid}` });

  const handleOnChange = (checked) => {
    trigger({ uuid, enabled: checked });
  };

  const label = enabled ? 'Alert enabled' : 'Alert disabled';

  return (
    <div className="flex items-center gap-2">
      <Switch checked={enabled} loading={isLoading} onChange={handleOnChange} />

      <div>{label}</div>
    </div>
  );
}

function IsLoading() {
  return (
    <NewHeader
      title={<Skeleton active paragraph={{ rows: 1 }} title={false} />}
    />
  );
}

function IsError({ error, onBack }) {
  const status = error?.status;

  if (status === 404) {
    return (
      <NewHeader
        prefix={<Lucide icon={ArrowLeft} onClick={onBack} />}
        title={<SectionTitle subtitle="--" title="--" />}
      />
    );
  }

  return false;
}

export default AlertDetailHeader;
