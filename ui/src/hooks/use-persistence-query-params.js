import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';

/**
 * Persists query parameters in localStorage between mounts/unmounts.
 *
 * Priority on mount: URL > localStorage. If a key is already present in the URL
 * (e.g. set by an explicit navigation), it is propagated to localStorage and the
 * URL is left untouched. Only when a key is missing from the URL we restore it
 * from localStorage.
 *
 * @param {string[]} keys - The query param keys you want to persist (e.g. ['from', 'to', 'preset'])
 * @param {string} storageKey - The prefix key used in localStorage
 */
export default function usePersistQueryParams(keys = [], storageKey = 'rbit-gw') {
  const [searchParams, setSearchParams] = useSearchParams();

  // ✅ On mount → URL wins; missing keys are restored from localStorage
  useEffect(() => {
    let didMutateUrl = false;

    keys.forEach((k) => {
      const fullKey = `${storageKey}-${k}`;
      const fromUrl = searchParams.get(k);

      if (fromUrl) {
        localStorage.setItem(fullKey, fromUrl);
        return;
      }

      const fromStorage = localStorage.getItem(fullKey);

      if (fromStorage) {
        searchParams.set(k, fromStorage);
        didMutateUrl = true;
      }
    });

    if (didMutateUrl) {
      setSearchParams(searchParams, { replace: true });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 💾 On unmount → save to localStorage
  useEffect(
    () => () => {
      keys.forEach((k) => {
        const val = searchParams.get(k);

        if (val) {
          localStorage.setItem(`${storageKey}-${k}`, val);
        } else {
          localStorage.removeItem(`${storageKey}-${k}`);
        }
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [searchParams],
  );

  // 💾 On refresh page → save to localStorage
  useEffect(() => {
    const handleBeforeUnload = () => {
      keys.forEach((k) => {
        const val = searchParams.get(k);
        const fullKey = `${storageKey}-${k}`;
        if (val) localStorage.setItem(fullKey, val);
        else localStorage.removeItem(fullKey);
      });
    };

    window.addEventListener('beforeunload', handleBeforeUnload);

    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, [keys, searchParams, storageKey]);
}
