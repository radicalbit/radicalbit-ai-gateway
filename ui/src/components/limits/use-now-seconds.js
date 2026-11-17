import { useEffect, useState } from 'react';

const TICK_MS = 30_000;

const nowSeconds = () => Date.now() / 1000;

// The current time in seconds, refreshed every 30 s: enough for "resets in N min".
function useNowSeconds() {
  const [now, setNow] = useState(nowSeconds);

  useEffect(() => {
    const interval = setInterval(() => {
      setNow(nowSeconds());
    }, TICK_MS);

    return () => {
      clearInterval(interval);
    };
  }, []);

  return now;
}

export default useNowSeconds;
