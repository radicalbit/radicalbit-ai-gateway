import useModals from '@Hooks/use-modals';
import { PathsEnum } from '@Src/constants';
import Lucide from '@Components/lucide';
import { useGetAssociableRoutesByGroupQuery, useGetGroupQuery } from '@State/groups/api';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Alert,
  FormField,
  Select,
  Skeleton,
} from '@radicalbit/radicalbit-design-system';
import { Search } from 'lucide-react';
import { Link } from 'react-router-dom';

function Routes() {
  const { modalPayload } = useModals();
  const groupUuid = modalPayload?.data?.uuid;
  const { form } = useFormbitContext();
  const projectUuid = form?.projectUuid;

  if (!projectUuid) {
    return <DisabledRoutesSelect />;
  }

  return <RoutesData groupUuid={groupUuid} projectUuid={projectUuid} />;
}

function RoutesData({ groupUuid, projectUuid }) {
  const { data = [], isLoading, isError, isSuccess } = useGetAssociableRoutesByGroupQuery({ groupUuid, projectUuid }, { skip: !groupUuid || !projectUuid });
  const routes = data.map((i) => ({ label: i.name, value: i.name }));

  if (isLoading) {
    return <Skeleton.Input active />;
  }

  if (isError) {
    return 'Something went wrong';
  }

  if (!isSuccess) {
    return false;
  }

  if (routes.length === 0) {
    return (
      <NoRoutesAlert />
    );
  }

  return (
    <RoutesInner routes={routes} />
  );
}

function DisabledRoutesSelect() {
  return (
    <FormField label="Routes">
      <Select
        disabled
        mode="multiple"
        placeholder="Select a project first"
      />
    </FormField>
  );
}

function RoutesInner({ routes }) {
  const { form, write, error } = useFormbitContext();
  const selected = form?.routes ?? [];

  const handleOnSelect = (value) => {
    write('routes', value);
  };

  return (
    <FormField label="Routes" message={error('routes')}>
      <Select
        filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())}
        mode="multiple"
        onChange={handleOnSelect}
        options={routes}
        placeholder={(
          <div className="flex flex-row items-center justify-between gap-4">
            <div>
              Select one or more routes
            </div>

            <Lucide icon={Search} />
          </div>
        )}
        value={selected}
      />
    </FormField>
  );
}

function NoRoutesAlert() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetGroupQuery(uuid);
  const name = data?.name;

  return (
    <FormField>
      <Alert
        description={(
          <span>
            {'All the available routes have been associated with the group '}

            <strong>{name}</strong>

            {'. Please go to the '}

            <Link className="c-anchor light" to={`/${PathsEnum.ROUTES}`}><strong>routes section</strong></Link>

            {' and create a new route if needed.'}
          </span>
        )}
        type="info"
      />
    </FormField>
  );
}

export default Routes;
