import useModals from '@Hooks/use-modals';
import { PathsEnum } from '@Src/constants';
import { useGetAssociableGroupsByRouteQuery } from '@State/routes/api';
import { faSearch } from '@fortawesome/free-solid-svg-icons';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Alert,
  FontAwesomeIcon,
  FormField,
  Select,
  Skeleton,
} from '@radicalbit/radicalbit-design-system';
import { Link, useSearchParams } from 'react-router-dom';

function Groups() {
  const { modalPayload } = useModals();
  const routeName = modalPayload?.data?.name;
  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const { data = [], isLoading, isError, isSuccess } = useGetAssociableGroupsByRouteQuery({ projectUuid, routeName }, { skip: !routeName || !projectUuid });
  const groups = data.map((i) => ({ label: i.name, value: i.uuid }));

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
    <GroupsInner groups={groups} />
  );
}

function GroupsInner({ groups }) {
  const { write } = useFormbitContext();

  const handleOnSelect = (value) => {
    write('groups', value);
  };

  return (
    <FormField>
      <Select
        filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())}
        mode="multiple"
        onChange={handleOnSelect}
        options={groups}
        placeholder={(
          <div className="flex flex-row items-center justify-between gap-4">
            <div>
              Select one or more groups
            </div>

            <FontAwesomeIcon icon={faSearch} />
          </div>
        )}
      />
    </FormField>
  );
}

function NoGroupsAlert() {
  const { modalPayload } = useModals();
  const name = modalPayload?.data?.name;

  return (
    <FormField>
      <Alert
        description={(
          <span>
            {'All the available groups have been associated with the route '}

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

export default Groups;
