import Lucide from '@Components/lucide';
import { useGetTagValuesByProjectQuery } from '@State/projects/api';
import { appendTagsToParams } from '@State/tags-query-params-factory';
import { Button, FormField, Select } from '@radicalbit/radicalbit-design-system';
import { CircleMinus } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { useTagsFilterContext } from './context';

const KEY_SELECT_WIDTH = 180;
const VALUE_SELECT_WIDTH = 260;

const writeRowsToSearchParams = (prev, rows) => {
  prev.delete('tags');

  appendTagsToParams(prev, rows);

  return prev;
};

function TagRow({ index, rowId, tagKeys }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const { rows, setRows } = useTagsFilterContext();

  const row = rows.find((item) => item.id === rowId);

  const { data, isError, isFetching } = useGetTagValuesByProjectQuery(
    { projectUuid, tagKey: row.key },
    { skip: !projectUuid || !row.key },
  );

  const valueOptions = (data?.tagValues ?? []).map((value) => ({ label: value, value }));

  const usedKeys = rows.map((item) => item.key).filter(Boolean);
  const keyOptions = tagKeys
    .filter((tagKey) => tagKey === row.key || !usedKeys.includes(tagKey))
    .map((tagKey) => ({ label: tagKey, value: tagKey }));

  const handleOnKeyChange = (value) => {
    setRows((prev) => {
      const next = prev.map((item) => {
        if (item.id !== rowId) {
          return item;
        }

        return { ...item, key: value, values: [] };
      });

      setSearchParams((current) => writeRowsToSearchParams(current, next));

      return next;
    });
  };

  const handleOnValuesChange = (values) => {
    setRows((prev) => {
      const next = prev.map((item) => {
        if (item.id !== rowId) {
          return item;
        }

        return { ...item, values };
      });

      setSearchParams((current) => writeRowsToSearchParams(current, next));

      return next;
    });
  };

  const handleOnRemove = () => {
    setRows((prev) => {
      if (prev.length === 1) {
        return prev;
      }

      const next = prev.filter((item) => item.id !== rowId);

      setSearchParams((current) => writeRowsToSearchParams(current, next));

      return next;
    });
  };

  return (
    <FormField label={`Tag ${index + 1}`}>
      <div className="flex flex-row items-center gap-2">
        <Select
          onChange={handleOnKeyChange}
          options={keyOptions}
          placeholder="Select key"
          style={{ width: KEY_SELECT_WIDTH }}
          value={row.key || undefined}
        />

        <Select
          allowClear
          disabled={!row.key || isError}
          loading={isFetching}
          maxTagCount="responsive"
          mode="multiple"
          onChange={handleOnValuesChange}
          options={valueOptions}
          placeholder="Select values"
          style={{ width: VALUE_SELECT_WIDTH }}
          value={row.values}
        />

        <Button
          disabled={rows.length === 1}
          onClick={handleOnRemove}
          prefix={<Lucide icon={CircleMinus} />}
          shape="circle"
          title="Remove"
          type="ghost"
        />
      </div>
    </FormField>
  );
}

export default TagRow;
