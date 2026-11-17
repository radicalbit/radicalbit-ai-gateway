import InfoPopover from '@Components/info-popover';
import { Tag } from '@radicalbit/radicalbit-design-system';

const VISIBLE_TAGS = 3;

function RequestTags({ tags }) {
  const visibleTags = tags.slice(0, VISIBLE_TAGS);
  const hiddenCount = tags.length - visibleTags.length;

  if (tags.length === 0) {
    return '--';
  }

  if (hiddenCount === 0) {
    return (
      <span className="inline-flex flex-wrap items-center gap-1">
        {visibleTags.map((tag) => <Tag key={tag} type="secondary">{tag}</Tag>)}
      </span>
    );
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {visibleTags.map((tag) => <Tag key={tag} type="secondary">{tag}</Tag>)}

      <InfoPopover
        content={(
          <div className="flex flex-col gap-1">
            {tags.map((tag) => <Tag key={tag} type="secondary">{tag}</Tag>)}
          </div>
        )}
        title="Tags"
      >
        <Tag rounded type="secondary">{`+${hiddenCount}`}</Tag>
      </InfoPopover>
    </span>
  );
}

export default RequestTags;
