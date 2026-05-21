import useModals from '@Hooks/use-modals';
import { PathsEnum } from '@Src/constants';
import { useGetAssociableKeysByGroupQuery, useGetGroupQuery } from '@State/groups/api';
import { faSearch } from '@fortawesome/free-solid-svg-icons';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Alert,
  FontAwesomeIcon,
  FormField,
  Select,
  Skeleton,
} from '@radicalbit/radicalbit-design-system';
import { Link } from 'react-router-dom';

function Keys() {
  const { modalPayload } = useModals();
  const groupUuid = modalPayload?.data?.uuid;
  const { data = [], isLoading, isError, isSuccess } = useGetAssociableKeysByGroupQuery({ groupUuid }, { skip: !groupUuid });
  const keys = data.map((i) => ({ label: i.name, value: i.uuid }));

  if (isLoading) {
    return <Skeleton.Input active />;
  }

  if (isError) {
    return 'Something went wrong';
  }

  if (!isSuccess) {
    return false;
  }

  if (keys.length === 0) {
    return (
      <NoKeysAlert />
    );
  }

  return (
    <KeysInner />
  );
}

function KeysInner() {
  const { write } = useFormbitContext();
  const { modalPayload } = useModals();
  const groupUuid = modalPayload?.data?.uuid;
  const { data = [] } = useGetAssociableKeysByGroupQuery({ groupUuid }, { skip: !groupUuid });
  const keys = data.map((i) => ({ label: i.name, value: i.uuid }));

  const handleOnSelect = (value) => {
    write('keys', value);
  };

  return (
    <FormField>
      <Select
        filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())}
        mode="multiple"
        onChange={handleOnSelect}
        options={keys}
        placeholder={(
          <div className="flex flex-row items-center justify-between gap-4">
            <div>
              Select one or more credentials
            </div>

            <FontAwesomeIcon icon={faSearch} />
          </div>
        )}
      />
    </FormField>
  );
}

function NoKeysAlert() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetGroupQuery(uuid);
  const name = data?.name;

  return (
    <FormField>
      <Alert
        description={(
          <span>
            {'All the available credentials have been associated with the group '}

            <strong>{name}</strong>

            {'. Please go to the '}

            <Link className="c-anchor light" to={`/${PathsEnum.CREDENTIALS}`}><strong>credentials section</strong></Link>

            {' and create a new credential if needed.'}
          </span>
        )}
        type="info"
      />
    </FormField>
  );
}

export default Keys;
