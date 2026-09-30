import { useSearchParams } from 'react-router-dom';
import McpInvocationsGraphDrillDown from './mcp-invocations-graph-drill-down';
import McpInvocationsGraphInner from './mcp-invocations-graph-inner';

function McpInvocationsGraph() {
  const [searchParams] = useSearchParams();
  const mcpDrillDownEntity = searchParams.get('mcpDrillDownEntity');
  const mcpDrillDownId = searchParams.get('mcpDrillDownId');

  const isDrillDown = mcpDrillDownEntity && mcpDrillDownId;

  if (isDrillDown) {
    return <McpInvocationsGraphDrillDown />;
  }

  return <McpInvocationsGraphInner />;
}

export default McpInvocationsGraph;
