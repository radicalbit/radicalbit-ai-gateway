import { REQUEST_TYPE_LABELS, RequestTypeEnum } from '@Src/constants';
import { Select } from '@radicalbit/radicalbit-design-system';
import { useSearchParams } from 'react-router-dom';

const REQUEST_TYPE_OPTIONS = Object.values(RequestTypeEnum)
  .map((value) => ({ label: REQUEST_TYPE_LABELS[value], value }));

function RequestTypeFilter({ id }) {
  const [searchParams, setSearchParams] = useSearchParams();

  const selectedRequestTypes = searchParams.get('requestType')
    ? searchParams.get('requestType').split(',')
    : [];

  const handleOnChange = (values) => {
    setSearchParams((prev) => {
      if (values.length === 0) {
        prev.delete('requestType');
      } else {
        prev.set('requestType', values.join(','));
      }
      return prev;
    });
  };

  return (
    <Select
      allowClear
      id={id}
      maxTagCount="responsive"
      mode="multiple"
      onChange={handleOnChange}
      options={REQUEST_TYPE_OPTIONS}
      placeholder="All types"
      style={{ width: 250 }}
      value={selectedRequestTypes}
    />
  );
}

export default RequestTypeFilter;
