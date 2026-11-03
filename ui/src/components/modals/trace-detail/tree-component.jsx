import { useEffect } from 'react';
import { formatMs } from '@Src/helpers/column-formatters';
import { Spin, Tree } from '@radicalbit/radicalbit-design-system';
import { useGetSpanByIdVertical } from '@State/tracing/vertical-hooks';
import { useSearchParams } from 'react-router-dom';
import { SPAN_PARAM } from './constants';

function TreeComponent({ traceId, tree, tree: { spanId } }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedSpanId = searchParams.get(SPAN_PARAM);

  const { isFetching } = useGetSpanByIdVertical({ traceId, spanId: selectedSpanId });

  useInitSelectedSpanId(spanId);

  const loadingSpanId = isFetching ? selectedSpanId : null;
  const treeData = [buildTreeData(tree, { loadingSpanId })];

  const handleOnSelect = (selectedKeys) => {
    if (selectedKeys.length > 0) {
      setSearchParams((prev) => {
        prev.set(SPAN_PARAM, selectedKeys[0]);
        return prev;
      });
    }
  };

  return (
    <Tree
      key={spanId}
      defaultExpandAll
      onSelect={handleOnSelect}
      selectedKeys={[selectedSpanId]}
      treeData={treeData}
    />
  );
}

function buildTreeData(node, { loadingSpanId }) {
  const errorCount = node?.errorCount || 0;
  const isLoading = node.spanId === loadingSpanId;

  const title = (function getTitle() {
    const label = `${node.spanName} (${formatMs(node.durationMs)})`;

    if (isLoading) {
      return (
        <Spin size="small" spinning>
          {label}
        </Spin>
      );
    }

    if (errorCount) {
      return <span className="is-error">{label}</span>;
    }

    return label;
  }());

  const treeNode = {
    title,
    key: node.spanId,
  };

  if (node.children && node.children.length > 0) {
    treeNode.children = node.children.map((child) => buildTreeData(child, { loadingSpanId }));
  }

  return treeNode;
}

const useInitSelectedSpanId = (spanId) => {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedSpanId = searchParams.get(SPAN_PARAM);

  useEffect(() => {
    if (!selectedSpanId && spanId) {
      setSearchParams((prev) => {
        prev.set(SPAN_PARAM, spanId);
        return prev;
      });
    }
  }, [selectedSpanId, spanId, setSearchParams]);
};

export default TreeComponent;
