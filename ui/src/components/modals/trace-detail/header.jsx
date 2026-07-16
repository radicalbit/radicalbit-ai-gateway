import Lucide from '@Components/lucide';
import useModals from '@Hooks/use-modals';
import { formatMs, formatInt } from '@Src/helpers/column-formatters';
import { useGetTraceByIdVertical } from '@State/tracing/vertical-hooks';
import {
  NewHeader, SectionTitle,
} from '@radicalbit/radicalbit-design-system';
import { ArrowLeft } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

function Header() {
  const { modalPayload } = useModals();
  const navigate = useNavigate();
  const traceId = modalPayload?.data?.traceId;
  const { data } = useGetTraceByIdVertical(traceId);

  const routeName = data?.routeName ?? '--';
  const groupName = data?.groupName ?? '--';
  const apiKeyName = data?.apiKeyName ?? '--';
  const subtitle = `${groupName} - ${apiKeyName}`;
  const duration = formatMs(data?.durationMs);
  const totalSpans = formatInt(data?.totalSpans);
  const errorCount = formatInt(data?.errorCount);
  const outputTokens = formatInt(data?.outputTokens);
  const inputTokens = formatInt(data?.inputTokens);
  const totalTokens = formatInt(data?.totalTokens);

  const handleOnClickBack = () => {
    const params = new URLSearchParams(window.location.search);
    params.delete('modal');
    params.delete('spanId');
    navigate(`?${params.toString()}`);
  };

  return (
    <NewHeader
      details={{
        one: (
          <SectionTitle align="center" reverse size="small" subtitle="Duration" title={duration} />
        ),
        two: (
          <SectionTitle align="center" reverse size="small" subtitle="Spans" title={totalSpans} />
        ),
        three: (
          <SectionTitle align="center" reverse size="small" subtitle="Errors" title={errorCount} />
        ),
        four: (
          <div className="flex flex-row gap-4">
            <SectionTitle align="center" reverse size="small" subtitle="Output" title={outputTokens} />

            <SectionTitle align="center" reverse size="small" subtitle="Input" title={inputTokens} />

            <SectionTitle align="center" reverse size="small" subtitle="Total Tokens" title={totalTokens} />
          </div>
        ),
      }}
      title={(
        <SectionTitle
          subtitle={subtitle}
          title={routeName}
          titlePrefix={<Lucide className="cursor-pointer" icon={ArrowLeft} onClick={handleOnClickBack} />}
        />
      )}
    />
  );
}

export default Header;
