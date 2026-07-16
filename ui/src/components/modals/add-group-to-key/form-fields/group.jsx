import useModals from '@Hooks/use-modals';
import { PathsEnum } from '@Src/constants';
import Lucide from '@Components/lucide';
import { useGetAssociableGroupsByKeyQuery, useGetKeyQuery } from '@State/keys/api';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Alert,
  FormField,
  Select,
  Skeleton,
  Tooltip,
} from '@radicalbit/radicalbit-design-system';
import { Key, Search } from 'lucide-react';
import { Link } from 'react-router-dom';

function Group() {
  const { modalPayload } = useModals();
  const keyUuid = modalPayload?.data?.uuid;

  const { data = [], isLoading, isError, isSuccess } = useGetAssociableGroupsByKeyQuery({ keyUuid }, { skip: !keyUuid });
  const groups = data.map((i) => {
    const keys = i?.keys || [];
    const keysLen = keys.length;

    return ({
      label: (
        <div className="flex justify-between gap-8 w-full">
          {i.name}

          <Tooltip title="Credentials already associated to that group">
            <small className="flex items-center gap-2">
              <Lucide icon={Key} />

              {keysLen}
            </small>
          </Tooltip>
        </div>),
      value: i.uuid,
    });
  });

  if (isLoading) {
    return <Skeleton.Input active />;
  }

  if (isError) {
    return 'Something went wrong';
  }

  if (!isSuccess) {
    return false;
  }

  if (groups.length === 0) {
    return (
      <NoGroupsAlert />
    );
  }

  return (
    <GroupInner groups={groups} />
  );
}

function GroupInner({ groups }) {
  const { write } = useFormbitContext();

  const handleOnSelect = (value) => {
    write('group', value);
  };

  return (
    <FormField>
      <Select
        filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())}
        onChange={handleOnSelect}
        options={groups}
        placeholder={(
          <div className="flex flex-row items-center justify-between gap-4">
            <div>
              Select one group
            </div>

            <Lucide icon={Search} />
          </div>
        )}
        showSearch
      />
    </FormField>
  );
}

function NoGroupsAlert() {
  const { modalPayload } = useModals();
  const keyUUID = modalPayload?.data?.uuid;

  const { data: key } = useGetKeyQuery(keyUUID, { skip: !keyUUID });
  const name = key?.name;

  return (
    <FormField>
      <Alert
        description={(
          <span>
            {'All the available groups have been associated with the credential '}

            <strong>{name}</strong>

            {'. Please go to the '}

            <Link className="c-anchor light" to={`/${PathsEnum.GROUPS}`}><strong>groups section</strong></Link>

            {' and create a new group if needed.'}
          </span>
        )}
        type="info"
      />
    </FormField>
  );
}

export default Group;
