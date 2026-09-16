const INITIAL_RETRY_DELAY_MS = 3000;
const MAX_RETRY_DELAY_MS = 60000;
const MAX_RETRIES = 5;

/**
 * @typedef {Object} Args
 * @property {string} url - Stream endpoint to subscribe to.
 * @property {(data: unknown) => void} onMessage - Called with the parsed payload of every message.
 * @property {(args: { isGivingUp: boolean }) => void} [onStreamError] - Called on every failed
 * connection. `isGivingUp` is true only on the last one, once no further retry is scheduled.
 *
 * @typedef {Object} Subscription
 * @property {() => void} close - Stops the stream and cancels any pending reconnection.
 */

/**
 * Subscribes to a Server-Sent Events endpoint with a capped exponential backoff.
 *
 * The native EventSource reconnects forever, roughly every 3 seconds. When the backend accepts the
 * connection and closes it immediately — which happens when a stream has nothing to emit — that
 * turns into an endless reconnection loop. This wrapper takes over the retry policy: it closes the
 * failed connection, waits a delay that doubles on every attempt, and stops after MAX_RETRIES.
 *
 * A connection that delivers at least one message is considered healthy, so its retry budget is
 * reset and a later drop gets the full set of attempts again.
 *
 * @param {Args} args - Function argument
 * @returns {Subscription} Handle used to tear the stream down.
 *
 * @example
 * const subscription = eventSourceWithBackoff({
 *   url,
 *   onMessage: (data) => updateCachedData(() => data),
 * });
 * await cacheEntryRemoved;
 * subscription.close();
 */
const eventSourceWithBackoff = ({ url, onMessage, onStreamError }) => {
  let eventSource = null;
  let retryTimeoutId = null;
  let retries = 0;
  let isClosed = false;

  const connect = () => {
    if (isClosed) {
      return;
    }

    eventSource = new EventSource(url, { withCredentials: true });

    eventSource.onmessage = ({ data }) => {
      retries = 0;

      const parsed = JSON.parse(data);

      onMessage(parsed);
    };

    eventSource.onerror = () => {
      eventSource.close();

      if (isClosed) {
        return;
      }

      const isGivingUp = retries >= MAX_RETRIES;

      if (onStreamError) {
        onStreamError({ isGivingUp });
      }

      if (isGivingUp) {
        return;
      }

      const delay = Math.min(INITIAL_RETRY_DELAY_MS * (2 ** retries), MAX_RETRY_DELAY_MS);

      retries += 1;
      retryTimeoutId = setTimeout(connect, delay);
    };
  };

  connect();

  return {
    close: () => {
      isClosed = true;

      clearTimeout(retryTimeoutId);

      if (eventSource) {
        eventSource.close();
      }
    },
  };
};

export default eventSourceWithBackoff;
