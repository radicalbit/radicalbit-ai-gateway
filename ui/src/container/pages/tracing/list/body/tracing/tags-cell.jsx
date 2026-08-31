import { Popover, Tag, Truncate } from '@radicalbit/radicalbit-design-system';

const VISIBLE_TAGS = 3;

const CELL_WIDTH = '150px';

function TagsCell({ tags }) {
  if (!tags?.length) {
    return '--';
  }

  const visibleTags = tags.slice(0, VISIBLE_TAGS);
  const hiddenCount = tags.length - visibleTags.length;

  return (
    <div className="flex flex-col gap-2">
      {visibleTags.map((tag) => (
        <i key={tag}>
          <Tag size="large" type="primary-outlined">
            <Truncate style={{ maxWidth: CELL_WIDTH }} tooltip={{ title: tag, placement: 'top' }}>{tag}</Truncate>
          </Tag>
        </i>
      ))}

      <HiddenTags count={hiddenCount} tags={tags} />
    </div>
  );
}

function HiddenTags({ count, tags }) {
  if (count <= 0) {
    return false;
  }

  const handleOnClick = (e) => {
    e.stopPropagation();
  };

  return (
    <Popover
      arrow={false}
      content={(
        <div className="flex flex-col gap-2">
          {tags.map((tag) => (
            <i key={tag}>
              <Tag size="large" type="primary-outlined">
                <Truncate style={{ maxWidth: CELL_WIDTH }} tooltip={{ title: tag, placement: 'top' }}>{tag}</Truncate>
              </Tag>
            </i>
          ))}
        </div>
      )}
      placement="topRight"
      title="Tags"
    >
      <Tag onClick={handleOnClick} rounded type="secondary">{`+${count}`}</Tag>
    </Popover>
  );
}

export default TagsCell;
