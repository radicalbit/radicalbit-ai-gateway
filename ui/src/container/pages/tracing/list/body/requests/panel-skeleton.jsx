import {
  Board, NewHeader, Skeleton,
} from '@radicalbit/radicalbit-design-system';

const SUMMARY_SKELETON_TITLE = { width: '80%' };

const STEPS_SKELETON_PARAGRAPH = { rows: 6 };

function PanelSkeleton() {
  return (
    <section aria-busy aria-label="Selected request" className="flex flex-col gap-4">
      <Skeleton active paragraph={false} title={SUMMARY_SKELETON_TITLE} />

      <Board
        header={(
          <NewHeader
            details={{ one: <Skeleton.Input active size="small" /> }}
            padding="none"
            title={<Skeleton.Input active size="small" />}
          />
        )}
        main={<Skeleton active paragraph={STEPS_SKELETON_PARAGRAPH} title={false} />}
        width="100%"
      />
    </section>
  );
}

export default PanelSkeleton;
