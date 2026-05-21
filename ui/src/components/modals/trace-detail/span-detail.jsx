import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import { formatTimestamp } from '@Helpers/column-formatters';
import useModals from '@Hooks/use-modals';
import { useGetSpanByIdVertical } from '@State/tracing/vertical-hooks';
import { Json, NewHeader, SectionTitle, Skeleton, Spinner } from '@radicalbit/radicalbit-design-system';
import { useSearchParams } from 'react-router-dom';

function SpanDetail() {
  const { modalPayload } = useModals();
  const traceId = modalPayload?.data?.traceId;

  const [searchParams] = useSearchParams();
  const selectedSpanId = searchParams.get('spanId');

  const { data, isLoading, isFetching, isError } = useGetSpanByIdVertical({ traceId, spanId: selectedSpanId });
  const attributes = data?.attributes;

  if (!selectedSpanId) {
    return <Placeholder />;
  }

  if (isError) {
    return <SomethingWentWrong size="small" />;
  }

  if (isLoading) {
    return (
      <Skeleton active block />
    );
  }

  const jsonData = attributes
    ? Object.entries(attributes).reduce((acc, [key, values]) => {
      try {
        return { ...acc, [key]: JSON.parse(values) };
      } catch (err) {
        return { ...acc, [key]: values };
      }
    }, {})
    : '';

  const isRefetching = isFetching && !isLoading;

  return (
    <Spinner spinning={isRefetching}>
      <Json data={jsonData} expandUntil={0} />
    </Spinner>
  );
}

function Placeholder() {
  return (
    <div className="flex items-center justify-center h-full">
      <span>Select a span from the tree to view its details.</span>
    </div>
  );
}

export function SpanHeader() {
  const { modalPayload } = useModals();
  const traceId = modalPayload?.data?.traceId;

  const [searchParams] = useSearchParams();
  const selectedSpanId = searchParams.get('spanId');

  const { data, isLoading, isFetching, isError } = useGetSpanByIdVertical({ traceId, spanId: selectedSpanId });
  const spanName = data?.spanName;
  const createdAt = data?.createdAt;
  const isRefetching = isFetching && !isLoading;

  if (isError || !selectedSpanId) {
    return (
      <NewHeader
        title={<SectionTitle size="small" title="Span Detail" />}
      />
    );
  }

  if (isLoading) {
    return (
      <NewHeader
        title={(
          <Skeleton.Input active />
        )}
      />
    );
  }

  return (
    <NewHeader
      title={(
        <div className={isRefetching ? 'opacity-50' : undefined}>
          <SectionTitle
            size="small"
            subtitle={formatTimestamp(createdAt)}
            title={spanName}
          />
        </div>
      )}
    />
  );
}

export default SpanDetail;
