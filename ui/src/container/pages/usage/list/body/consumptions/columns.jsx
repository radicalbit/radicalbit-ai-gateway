import { Popover } from '@radicalbit/radicalbit-design-system';

const columns = [
  {
    title: '',
    dataIndex: 'label',
    key: 'label',
    render: (value) => <span className="font-semibold">{value}</span>,
  },
  {
    title: 'Chat models',
    dataIndex: 'chatModels',
    key: 'chatModels',
  },
  {
    title: 'Judge',
    dataIndex: 'judge',
    key: 'judge',
  },
  {
    title: 'Embedding',
    dataIndex: 'embedding',
    key: 'embedding',
  },
  {
    title: 'Semantic cache',
    dataIndex: 'semanticCache',
    key: 'semanticCache',
  },
  {
    title: 'Transcription',
    dataIndex: 'transcription',
    key: 'transcription',
    render: (value) => <TranscriptionCell value={value} />,
  },
  {
    title: 'Total',
    dataIndex: 'total',
    key: 'total',
  },
];

function TranscriptionCell({ value }) {
  if (typeof value === 'string') {
    return value;
  }

  return (
    <Popover
      content={<TranscriptionPopoverContent value={value} />}
      minWidth="250"
      title="Transcription"
    >
      <div className="underline decoration-dotted cursor-default w-fit">{value?.total}</div>
    </Popover>
  );
}

function TranscriptionPopoverContent({ value }) {
  const duration = value?.duration;
  const audio = value?.audio;
  const text = value?.text;

  return (
    <div className="flex flex-col gap-1">
      <PopoverRow label="Duration:" value={duration} />

      <PopoverRow label="Audio:" value={audio} />

      <PopoverRow label="Text:" value={text} />
    </div>
  );
}

function PopoverRow({ label, value }) {
  return (
    <div className="flex justify-between gap-2">
      <div>{label}</div>

      <div>{value}</div>
    </div>
  );
}

export default columns;
