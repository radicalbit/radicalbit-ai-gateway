import IconBadge from '@Components/icon-badge';
import Lucide from '@Components/lucide';
import { useGetRouteByNameWithRange } from '@Src/store/state/routes/vertical-hooks';
import {
  Json, Popover,
} from '@radicalbit/radicalbit-design-system';
import isEmpty from 'lodash/isEmpty';
import {
  Bot, CircleCheck, CornerDownRight, Hourglass, Route, Shield, TableColumnsSplit, Timer,
} from 'lucide-react';
import { useParams } from 'react-router-dom';

// *** Models ***
export function useGetModelItem() {
  const { name } = useParams();

  const { data } = useGetRouteByNameWithRange(name);
  const chatModels = data?.configuration?.chatModels;
  const embeddingModels = data?.configuration?.embeddingModels;
  const transcriptionModels = data?.configuration?.transcriptionModels;

  if (isEmpty(chatModels) && isEmpty(embeddingModels) && isEmpty(transcriptionModels)) {
    return {
      collapsible: 'disabled',
      showArrow: false,
      label: (
        <Popover content="Configure this section into your configuration file" placement="top">
          <div className="flex justify-start items-center gap-4">
            <IconBadge aria-label="Models" type="text"><Lucide icon={Bot} /></IconBadge>

            <div>Models</div>
          </div>
        </Popover>
      ),
    };
  }

  return {
    label: (
      <div className="flex justify-start items-center gap-4">
        <IconBadge aria-label="Models" type="text"><Lucide icon={Bot} /></IconBadge>

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
  const transcriptionModels = data?.configuration?.transcriptionModels || [];

  return <Json data={{ chatModels, embeddingModels, transcriptionModels }} />;
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
            <IconBadge aria-label="Fallback" disabled type="secondary-light"><Lucide icon={CornerDownRight} /></IconBadge>

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
        <IconBadge aria-label="Fallback" {...type}><Lucide icon={CornerDownRight} /></IconBadge>

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
            <IconBadge aria-label="Guardrails" disabled type="secondary-light"><Lucide icon={Shield} /></IconBadge>

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
        <IconBadge aria-label="Guardrails" {...type}><Lucide icon={Shield} /></IconBadge>

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
            <IconBadge aria-label="Rate Limiting" disabled><Lucide icon={Timer} /></IconBadge>

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
        <IconBadge aria-label="Rate Limiting" {...type}><Lucide icon={Timer} /></IconBadge>

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
  const chatModels = data?.configuration?.chatModels;
  const embeddingModels = data?.configuration?.embeddingModels;

  if (isEmpty(tokenLimiting)) {
    const tooltip = isEmpty(chatModels) && isEmpty(embeddingModels)
      ? 'Requires a chat or embedding model on this route'
      : 'Configure this section into your configuration file';

    return {
      collapsible: 'disabled',
      showArrow: false,
      label: (
        <Popover content={tooltip} placement="top">
          <div className="flex justify-start items-center gap-4">
            <IconBadge aria-label="Token Limiting" disabled type="secondary-light"><Lucide icon={TableColumnsSplit} /></IconBadge>

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
        <IconBadge aria-label="Token Limiting" {...type}><Lucide icon={TableColumnsSplit} /></IconBadge>

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

// *** DurationLimiting ***
export function useGetDurationLimitingItem() {
  const { name } = useParams();

  const { data } = useGetRouteByNameWithRange(name);
  const durationLimiting = data?.configuration?.durationLimiting;
  const transcriptionModels = data?.configuration?.transcriptionModels;

  if (isEmpty(durationLimiting)) {
    const tooltip = isEmpty(transcriptionModels)
      ? 'Requires a transcription model on this route'
      : 'Configure this section into your configuration file';

    return {
      collapsible: 'disabled',
      showArrow: false,
      label: (
        <Popover content={tooltip} placement="top">
          <div className="flex justify-start items-center gap-4">
            <IconBadge aria-label="Duration Limiting" disabled><Lucide icon={Hourglass} /></IconBadge>

            <div>Duration Limiting</div>
          </div>
        </Popover>
      ),
    };
  }

  const durationLimitTriggered = data?.metrics?.durationLimitTriggered;
  const type = (function getType() {
    if (durationLimitTriggered > 0) {
      return { type: 'primary' };
    } if (!durationLimitTriggered) {
      return { type: 'primary-light' };
    }
    return { disabled: true };
  }());

  return {
    label: (
      <div className="flex justify-start items-center gap-4">
        <IconBadge aria-label="Duration Limiting" {...type}><Lucide icon={Hourglass} /></IconBadge>

        <div>Duration Limiting</div>
      </div>
    ),
  };
}

export function DurationLimiting() {
  const { name } = useParams();

  const { data } = useGetRouteByNameWithRange(name);
  const durationLimiting = data?.configuration?.durationLimiting;

  return <Json data={durationLimiting} />;
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
            <IconBadge aria-label="Caching" {...type}>
              <Lucide icon={CircleCheck} />
            </IconBadge>

            <div>Caching</div>
          </div>
        </Popover>
      ),
    };
  }

  return {
    label: (
      <div className="flex justify-start items-center gap-4">
        <IconBadge aria-label="Caching" {...type}>
          <Lucide icon={CircleCheck} />
        </IconBadge>

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
            <IconBadge aria-label="Advanced Routing" disabled type="secondary-light"><Lucide icon={Route} /></IconBadge>

            <div>Advanced Routing</div>
          </div>
        </Popover>
      ),
    };
  }

  return {
    label: (
      <div className="flex justify-start items-center gap-4">
        <IconBadge aria-label="Advanced Routing" type="text"><Lucide icon={Route} /></IconBadge>

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
