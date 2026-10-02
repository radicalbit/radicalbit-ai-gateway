import useModals from '@Hooks/use-modals';
import { useGetTraceByIdVertical } from '@State/tracing/vertical-hooks';
import { Popover, SectionTitle } from '@radicalbit/radicalbit-design-system';

function TraceTags() {
  const { modalPayload } = useModals();
  const traceId = modalPayload?.data?.traceId;

  const { data } = useGetTraceByIdVertical(traceId);
  const tags = data?.tags;

  if (!tags?.length) {
    return <SectionTitle align="center" reverse size="small" subtitle="Tags" title="--" />;
  }

  return (
    <Popover
      arrow={false}
      content={(
        <div className="flex flex-col gap-1 font-mono text-xs">
          {tags.map((tag) => <span key={tag}>{tag}</span>)}
        </div>
      )}
      placement="bottom"
      title="Tags"
    >
      <div className="cursor-pointer">
        <SectionTitle
          align="center"
          reverse
          size="small"
          subtitle="Tags"
          title={<span className="underline decoration-dotted">{tags.length}</span>}
        />
      </div>
    </Popover>
  );
}

export default TraceTags;
