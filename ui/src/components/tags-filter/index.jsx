import { useGetTagKeysByProjectQuery } from '@State/projects/api';
import {
  Button, Divider, Popover, Select, Skeleton, Void,
} from '@radicalbit/radicalbit-design-system';
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { EMPTY_ROW, TagsFilterContextProvider, useTagsFilterContext } from './context';
import TagRow from './tag-row';

const POPOVER_MIN_WIDTH = 520;

const OVERLAY_SELECTORS = '.c-popover, .ant-select-dropdown';

const TRIGGER_WIDTH = 150;

const OPEN_KEYS = ['Enter', ' ', 'ArrowDown'];

function TagsFilter({ id }) {
  return (
    <TagsFilterContextProvider>
      <TagsFilterInner id={id} />
    </TagsFilterContextProvider>
  );
}

function TagsFilterInner({ id }) {
  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const { rows } = useTagsFilterContext();
  const activeCount = rows.filter(({ key, values }) => key && values.length > 0).length;
  const label = activeCount > 0 ? `${activeCount} selected` : undefined;

  const { handleOnTriggerClick, handleOnTriggerKeyDown, isOpen, wrapperRef } = usePopoverVisibility();
  useResetRowsOnProjectChange();

  if (!projectUuid) {
    return (
      <Select
        disabled
        id={id}
        minWidth={TRIGGER_WIDTH}
        placeholder="Select a project first"
      />
    );
  }

  return (
    <Popover
      content={<PopoverContent />}
      minWidth={POPOVER_MIN_WIDTH}
      open={isOpen}
      placement="bottomLeft"
      trigger={[]}
    >
      <div ref={wrapperRef}>
        <Select
          id={id}
          minWidth={TRIGGER_WIDTH}
          onClick={handleOnTriggerClick}
          onKeyDown={handleOnTriggerKeyDown}
          open={false}
          placeholder="All tags"
          value={label}
        />
      </div>
    </Popover>
  );
}

function PopoverContent() {
  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const { data, isError, isLoading, isSuccess } = useGetTagKeysByProjectQuery({ projectUuid });

  if (isLoading) {
    return <Skeleton.Input active block />;
  }

  if (isError) {
    return <Void description="Unable to load tags for this project" size="small" />;
  }

  if (!data?.tagKeys?.length) {
    return <Void description="No tags found for this project" size="small" />;
  }

  if (!isSuccess) {
    return false;
  }

  return <IsSuccess tagKeys={data.tagKeys} />;
}

function IsSuccess({ tagKeys }) {
  const { rows, setRows } = useTagsFilterContext();

  const nextRowId = useRef(0);

  const usedKeys = rows.map((row) => row.key).filter(Boolean);
  const isAddDisabled = usedKeys.length >= tagKeys.length;

  const handleOnAddRow = () => {
    nextRowId.current += 1;

    setRows((prev) => [...prev, { id: `new-${nextRowId.current}`, key: undefined, values: [] }]);
  };

  return (
    <div className="flex flex-col gap-2">
      {rows.map((row, index) => (
        <TagRow key={row.id} index={index} rowId={row.id} tagKeys={tagKeys} />
      ))}

      <Divider />

      <div className="flex flex-row">
        <Button disabled={isAddDisabled} onClick={handleOnAddRow}>
          + Add another tag
        </Button>
      </div>
    </div>
  );
}

const usePopoverVisibility = () => {
  const [isOpen, setIsOpen] = useState(false);
  const wrapperRef = useRef(null);

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    const handleOnDocumentClick = (event) => {
      if (wrapperRef.current?.contains(event.target)) {
        return;
      }

      const isInsideOverlay = Array.from(document.querySelectorAll(OVERLAY_SELECTORS))
        .some((overlay) => overlay.contains(event.target));

      if (isInsideOverlay) {
        return;
      }

      setIsOpen(false);
    };

    const handleOnDocumentKeyDown = (event) => {
      if (event.key !== 'Escape' || document.querySelector('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')) {
        return;
      }

      setIsOpen(false);
      wrapperRef.current?.querySelector('input')?.focus();
    };

    document.addEventListener('mousedown', handleOnDocumentClick, true);
    document.addEventListener('keydown', handleOnDocumentKeyDown);

    return () => {
      document.removeEventListener('mousedown', handleOnDocumentClick, true);
      document.removeEventListener('keydown', handleOnDocumentKeyDown);
    };
  }, [isOpen]);

  const handleOnTriggerClick = () => {
    setIsOpen((prev) => !prev);
  };

  const handleOnTriggerKeyDown = (event) => {
    if (!OPEN_KEYS.includes(event.key)) {
      return;
    }

    event.preventDefault();
    setIsOpen(true);

    requestAnimationFrame(() => {
      document.querySelector('.c-popover:not(.ant-popover-hidden) input, .c-popover:not(.ant-popover-hidden) button')?.focus();
    });
  };

  return {
    handleOnTriggerClick, handleOnTriggerKeyDown, isOpen, wrapperRef,
  };
};

const useResetRowsOnProjectChange = () => {
  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const { setRows } = useTagsFilterContext();

  const previousProjectUuid = useRef(projectUuid);

  useEffect(() => {
    if (previousProjectUuid.current === projectUuid) {
      return;
    }

    previousProjectUuid.current = projectUuid;

    setRows([EMPTY_ROW]);
  }, [projectUuid, setRows]);
};

export default TagsFilter;
