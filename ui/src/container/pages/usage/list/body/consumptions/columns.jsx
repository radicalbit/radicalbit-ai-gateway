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
    title: 'Total',
    dataIndex: 'total',
    key: 'total',
  },
];

export default columns;
