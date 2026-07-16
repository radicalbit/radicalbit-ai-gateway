import Lucide from '@Components/lucide';
import { PathsEnum } from '@Src/constants';
import { useGetAlertQuery } from '@State/alerts/api';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  Board, Button, Collapse, FormField, Skeleton, Spinner, Void,
} from '@radicalbit/radicalbit-design-system';
import { TriangleAlert } from 'lucide-react';
import { useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Channel from './form-fields/channel';
import Description from './form-fields/description';
import Event from './form-fields/event';
import Name from './form-fields/name';
import Project from './form-fields/project';
import Recipient from './form-fields/recipient';
import Route from './form-fields/route';
import Scope from './form-fields/scope';
import TimeAggregation from './form-fields/time-aggregation';
import { schema } from './schema';
import useHandleOnSubmit from './useHandleOnSubmit';

function AlertDetail() {
  const { uuid } = useParams();
  const { isError, error, refetch, isSuccess, isLoading } = useGetAlertQuery(uuid);

  if (isLoading) {
    return <IsLoading />;
  }

  if (isError) {
    return <IsError error={error} refetch={refetch} />;
  }

  if (!isSuccess) {
    return false;
  }

  return (
    <FormbitContextProvider initialValues={{}} schema={schema}>
      <AlertDetailForm />
    </FormbitContextProvider>
  );
}

function AlertDetailForm() {
  const { error } = useFormbitContext();
  const { isLoading: isInitializing } = useInitializeForm();

  return (
    <Spinner isFormWrapper spinning={isInitializing}>
      <div className="flex flex-col gap-4">
        <Board
          main={<Name />}
          noBackground
          secondary={<Description />}
          size="small"
        />

        <Collapse
          defaultActiveKey={['rule']}
          items={[{
            key: 'rule',
            label: 'Rule',
            children: (
              <div className="flex flex-col gap-4">
                <Scope />

                <Project />

                <Route />

                <Event />
              </div>
            ),
          }]}
          type="no-border"
        />

        <Collapse
          defaultActiveKey={['time-aggregation']}
          items={[{
            key: 'time-aggregation',
            label: 'Time aggregation',
            children: <TimeAggregation />,
          }]}
          type="no-border"
        />

        <Collapse
          defaultActiveKey={['channel']}
          items={[{
            key: 'channel',
            label: 'Channel and recipient',
            children: (
              <div className="flex flex-col gap-4">
                <Channel />

                <Recipient />
              </div>
            ),
          }]}
          type="no-border"
        />

        {error('silent.backend') && <FormField message={error('silent.backend')} />}

        <div className="pr-4">
          <Actions />
        </div>
      </div>
    </Spinner>
  );
}

function Actions() {
  const { handleOnSubmit, args: { isLoading }, isSubmitDisabled } = useHandleOnSubmit();

  return (
    <div className="flex justify-between">
      <div />

      <Button
        disabled={isSubmitDisabled}
        loading={isLoading}
        onClick={handleOnSubmit}
        type="primary"
      >
        Save
      </Button>
    </div>
  );
}

function IsLoading() {
  return (
    <div className="flex flex-col gap-4">
      <Skeleton active paragraph={{ rows: 2 }} />

      <Skeleton active paragraph={{ rows: 4 }} />
    </div>
  );
}

function IsError({ refetch, error }) {
  const navigate = useNavigate();
  const status = error?.status;

  const handleOnBack = () => {
    const { search } = window.location;
    navigate(`/${PathsEnum.ALERTS}${search}`);
  };

  if (status === 404) {
    return (
      <Board
        main={(
          <Void
            actions={<Button onClick={handleOnBack}>Back</Button>}
            description={(
              <>
                The alert rule does not exist or
                <br />
                might be deleted
              </>
            )}
            image={<Lucide icon={TriangleAlert} />}
            title="Alert rule not found"
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
          image={<Lucide icon={TriangleAlert} />}
          title="Unable to load alert rule"
        />
      )}
    />
  );
}

const useInitializeForm = () => {
  const { uuid } = useParams();
  const { data, ...rest } = useGetAlertQuery(uuid);
  const { initialize } = useFormbitContext();

  useEffect(() => {
    if (data) {
      initialize({
        name: data.name,
        description: data.description ?? '',
        project: data.project,
        route: data.route,
        event: data.event,
        recipients: data.recipients ?? [],
      });
    }
  }, [initialize, data]);

  return rest;
};

export default AlertDetail;
