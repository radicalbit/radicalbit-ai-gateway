import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
} from 'react';

const VisibleRowsContext = createContext(null);

const NO_UUIDS = [];

/**
 * @typedef {object} VisibleRowsProviderProps
 * @property {React.ReactNode} children
 */

/**
 * Tracks the rows a list shows right now, whatever its page, sort and search, so a
 * consumption stream is opened for the visible page only. A row registers while it is
 * mounted (`useRegisterVisibleRow`); consumers read the sorted uuids (`useVisibleRowUuids`).
 *
 * @param {VisibleRowsProviderProps} props
 */
export function VisibleRowsProvider({ children }) {
  const [uuids, setUuids] = useState(NO_UUIDS);

  const register = useCallback((uuid) => {
    setUuids((previous) => [...previous, uuid].sort());

    return () => {
      setUuids((previous) => previous.filter((other) => other !== uuid));
    };
  }, []);

  const value = useMemo(() => ({ register, uuids }), [register, uuids]);

  return <VisibleRowsContext.Provider value={value}>{children}</VisibleRowsContext.Provider>;
}

/**
 * The uuids of the rows registered right now, sorted, so every reader passes the same
 * stream args and shares one subscription.
 *
 * @returns {string[]}
 */
export function useVisibleRowUuids() {
  return useContext(VisibleRowsContext)?.uuids ?? NO_UUIDS;
}

/**
 * Registers *uuid* as visible while the calling row is mounted. Pass nothing for a row
 * that has nothing to stream.
 *
 * @param {string} [uuid]
 */
export function useRegisterVisibleRow(uuid) {
  const register = useContext(VisibleRowsContext)?.register;

  useEffect(() => {
    if (!uuid || !register) {
      return undefined;
    }

    return register(uuid);
  }, [register, uuid]);
}
