import {
  Board, NewHeader, Skeleton,
} from '@radicalbit/radicalbit-design-system';

function PanelSkeleton() {
  return (
    <section aria-busy aria-label="Selected request" className="flex flex-col gap-4">
      <Skeleton active paragraph={false} title={{ width: '80%' }} />

      <Board
        header={(
          <NewHeader
            details={{ one: <Skeleton.Input active size="small" /> }}
            padding="none"
            title={<Skeleton.Input active size="small" />}
          />
        )}
        main={<Skeleton active paragraph={{ rows: 6 }} title={false} />}
        width="100%"
      />
    </section>
  );
}

export default PanelSkeleton;
