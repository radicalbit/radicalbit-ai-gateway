import { useGetRouteByNameWithRange } from '@Src/store/state/routes/vertical-hooks';
import {
  faArrowsTurnRight,
  faCheckCircle,
  faRobot, faRoute, faShield, faStopwatch,
  faTableCellsColumnLock,
} from '@fortawesome/free-solid-svg-icons';
import {
  Button, FontAwesomeIcon, Json, Popover,
} from '@radicalbit/radicalbit-design-system';
import isEmpty from 'lodash/isEmpty';
import { useParams } from 'react-router-dom';

// *** Models ***
export function useGetModelItem() {
  const { name } = useParams();

  const { data } = useGetRouteByNameWithRange(name);
  const chatModels = data?.configuration?.chatModels;
  const embeddingModels = data?.configuration?.embeddingModels;

  if (isEmpty(chatModels) && isEmpty(embeddingModels)) {
    return {
      collapsible: 'disabled',
      showArrow: false,
      label: (
        <Popover content="Configure this section into your configuration file" placement="top">
          <div className="flex justify-start items-center gap-4">
            <Button shape="circle" type="text"><FontAwesomeIcon icon={faRobot} /></Button>

            <div>Models</div>
          </div>
        </Popover>
      ),
    };
  }

  return {
    label: (
      <div className="flex justify-start items-center gap-4">
        <Button shape="circle" type="text"><FontAwesomeIcon icon={faRobot} /></Button>

        <div>Models</div>
      </div>
    ),
  };
}

export function Models() {
  const { name } = useParams();

  const { data } = useGetRouteByNameWithRange(name);
  const chatModels = data?.configuration?.chatModels || [];
  const embeddingModels = data?.configuration?.embeddingModels || [];

  return <Json data={{ chatModels, embeddingModels }} />;
}

// *** Fallback ***
export function useGetFallbackItem() {
  const { name } = useParams();

  const { data } = useGetRouteByNameWithRange(name);
  const fallback = data?.configuration?.fallback;

  if (isEmpty(fallback)) {
    return {
      collapsible: 'disabled',
      showArrow: false,
      label: (
        <Popover content="Configure this section into your configuration file" placement="top">
          <div className="flex justify-start items-center gap-4">
            <Button disabled shape="circle" type="secondary-light"><FontAwesomeIcon icon={faArrowsTurnRight} /></Button>

            <div>Fallback</div>
          </div>
        </Popover>
      ),
    };
  }

  const value = data?.metrics?.fallbacks?.value;

  const type = (function getType() {
    if (value > 0) {
      return { type: 'primary' };
    }
    if (value === 0) {
      return { type: 'primary-light' };
    }
    return { disabled: true };
  }());

  return {
    label: (
      <div className="flex justify-start items-center gap-4">
        <Button shape="circle" {...type}><FontAwesomeIcon icon={faArrowsTurnRight} /></Button>

        <div>Fallback</div>
      </div>
    ),
  };
}

export function Fallback() {
  const { name } = useParams();

  const { data } = useGetRouteByNameWithRange(name);
  const fallback = data?.configuration?.fallback;

  return <Json data={fallback} />;
}

// *** Guardrails ***
export function useGetGuardrailsItem() {
  const { name } = useParams();

  const { data } = useGetRouteByNameWithRange(name);
  const guardrails = data?.configuration?.guardrails;

  if (isEmpty(guardrails)) {
    return {
      collapsible: 'disabled',
      showArrow: false,
      label: (
        <Popover content="Configure this section into your configuration file" placement="top">
          <div className="flex justify-start items-center gap-4">
            <Button disabled shape="circle" type="secondary-light"><FontAwesomeIcon icon={faShield} /></Button>

            <div>Guardrails</div>
          </div>
        </Popover>
      ),
    };
  }

  const value = data?.metrics?.guardrails?.value;
  const type = (function getType() {
    if (value > 0) {
      return { type: 'primary' };
    }
    if (value === 0) {
      return { type: 'primary-light' };
    }
    return { disabled: true };
  }());

  return {
    label: (
      <div className="flex justify-start items-center gap-4">
        <Button shape="circle" {...type}><FontAwesomeIcon icon={faShield} /></Button>

        <div>Guardrails</div>
      </div>
    ),
  };
}

export function Guardrails() {
  const { name } = useParams();

  const { data } = useGetRouteByNameWithRange(name);
  const guardrails = data?.configuration?.guardrails;

  return <Json data={guardrails} />;
}

// *** RateLimiting ***
export function useGetRateLimitingItem() {
  const { name } = useParams();

  const { data } = useGetRouteByNameWithRange(name);
  const rateLimiting = data?.configuration?.rateLimiting;

  if (isEmpty(rateLimiting)) {
    return {
      collapsible: 'disabled',
      showArrow: false,
      label: (
        <Popover content="Configure this section into your configuration file" placement="top">
          <div className="flex justify-start items-center gap-4">
            <Button disabled shape="circle"><FontAwesomeIcon icon={faStopwatch} /></Button>

            <div>Rate Limiting</div>
          </div>
        </Popover>
      ),
    };
  }

  const rateLimitTriggered = data?.metrics?.rateLimitTriggered;
  const type = (function getType() {
    if (rateLimitTriggered > 0) {
      return { type: 'primary' };
    } if (!rateLimitTriggered) {
      return { type: 'primary-light' };
    }
    return { disabled: true };
  }());

  return {
    label: (
      <div className="flex justify-start items-center gap-4">
        <Button shape="circle" {...type}><FontAwesomeIcon icon={faStopwatch} /></Button>

        <div>Rate Limiting</div>
      </div>
    ),
  };
}

export function RateLimiting() {
  const { name } = useParams();

  const { data } = useGetRouteByNameWithRange(name);
  const rateLimiting = data?.configuration?.rateLimiting;

  return <Json data={rateLimiting} />;
}

// *** TokenLimiting ***
export function useGetTokenLimitingItem() {
  const { name } = useParams();

  const { data } = useGetRouteByNameWithRange(name);
  const tokenLimiting = data?.configuration?.tokenLimiting;
  const tokenInputLimitTriggered = data?.metrics?.tokenInputLimitTriggered;
  const tokenOutputLimitTriggered = data?.metrics?.tokenOutputLimitTriggered;

  if (isEmpty(tokenLimiting)) {
    return {
      collapsible: 'disabled',
      showArrow: false,
      label: (
        <Popover content="Configure this section into your configuration file" placement="top">
          <div className="flex justify-start items-center gap-4">
            <Button disabled shape="circle" type="secondary-light"><FontAwesomeIcon icon={faTableCellsColumnLock} /></Button>

            <div>Token Limiting</div>
          </div>
        </Popover>
      ),
    };
  }

  const type = (function getType() {
    if (tokenInputLimitTriggered > 0 || tokenOutputLimitTriggered > 0) {
      return { type: 'primary' };
    } if (!tokenInputLimitTriggered && !tokenOutputLimitTriggered) {
      return { type: 'primary-light' };
    }
    return { disabled: true };
  }());

  return {
    label: (
      <div className="flex justify-start items-center gap-4">
        <Button shape="circle" {...type}><FontAwesomeIcon icon={faTableCellsColumnLock} /></Button>

        <div>Token Limiting</div>
      </div>
    ),
  };
}

export function TokenLimit() {
  const { name } = useParams();

  const { data } = useGetRouteByNameWithRange(name);
  const tokenLimiting = data?.configuration?.tokenLimiting;

  return <Json data={tokenLimiting} />;
}

// *** Caching ***
export function useGetCacheItem() {
  const { name } = useParams();

  const { data } = useGetRouteByNameWithRange(name);
  const caching = data?.configuration?.caching;
  const cacheTriggered = data?.metrics?.cacheTriggered;

  const type = (function getType() {
    if (cacheTriggered > 0) {
      return { type: 'primary' };
    }
    if (cacheTriggered === 0) {
      return { type: 'primary-light' };
    }
    return { disabled: true };
  }());

  if (isEmpty(caching)) {
    return {
      collapsible: 'disabled',
      showArrow: false,
      label: (
        <Popover content="Configure this section into your configuration file" placement="top">
          <div className="flex justify-start items-center gap-4">
            <Button shape="circle" {...type}>
              <FontAwesomeIcon icon={faCheckCircle} />
            </Button>

            <div>Caching</div>
          </div>
        </Popover>
      ),
    };
  }

  return {
    label: (
      <div className="flex justify-start items-center gap-4">
        <Button shape="circle" {...type}>
          <FontAwesomeIcon icon={faCheckCircle} />
        </Button>

        <div>Caching</div>
      </div>
    ),
  };
}

export function Cache() {
  const { name } = useParams();

  const { data } = useGetRouteByNameWithRange(name);
  const cache = data?.configuration?.caching;

  return <Json data={cache} />;
}

// *** Advanced Routing ***
export function useGetAdvancedRoutingItem() {
  const { name } = useParams();

  const { data } = useGetRouteByNameWithRange(name);
  const routing = data?.configuration?.routing;

  if (isEmpty(routing)) {
    return {
      collapsible: 'disabled',
      showArrow: false,
      label: (
        <Popover content="Configure this section into your configuration file" placement="top">
          <div className="flex justify-start items-center gap-4">
            <Button disabled shape="circle" type="secondary-light"><FontAwesomeIcon icon={faRoute} /></Button>

            <div>Advanced Routing</div>
          </div>
        </Popover>
      ),
    };
  }

  return {
    label: (
      <div className="flex justify-start items-center gap-4">
        <Button shape="circle" type="text"><FontAwesomeIcon icon={faRoute} /></Button>

        <div>Advanced Routing</div>
      </div>
    ),
  };
}

export function AdvancedRouting() {
  const { name } = useParams();

  const { data } = useGetRouteByNameWithRange(name);
  const routing = data?.configuration?.routing;

  return <Json data={routing} />;
}
