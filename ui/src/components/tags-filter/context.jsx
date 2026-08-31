import { parseTagsFromSearchParams } from '@State/tags-query-params-factory';
import {
  createContext, useContext, useMemo, useState,
} from 'react';
import { useSearchParams } from 'react-router-dom';

export const EMPTY_ROW = { id: 'empty', key: undefined, values: [] };

const buildRowsFromSearchParams = (searchParams) => {
  const rows = parseTagsFromSearchParams(searchParams)
    .map((tag, index) => ({ id: `${tag.key}-${index}`, key: tag.key, values: tag.values }));

  if (rows.length === 0) {
    return [EMPTY_ROW];
  }

  return rows;
};

const TagsFilterContext = createContext(null);

export const useTagsFilterContext = () => useContext(TagsFilterContext);

export function TagsFilterContextProvider({ children }) {
  const [searchParams] = useSearchParams();

  const [rows, setRows] = useState(() => buildRowsFromSearchParams(searchParams));

  const value = useMemo(() => ({ rows, setRows }), [rows]);

  return (
    <TagsFilterContext.Provider value={value}>
      {children}
    </TagsFilterContext.Provider>
  );
}
