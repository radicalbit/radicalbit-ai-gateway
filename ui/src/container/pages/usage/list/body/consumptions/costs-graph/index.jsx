import { useSearchParams } from 'react-router-dom';
import CostsGraphDrillDown from './costs-graph-drill-down';
import CostsGraphInner from './costs-graph-inner';

function CostsGraph() {
  const [searchParams] = useSearchParams();
  const drillDownEntity = searchParams.get('drillDownEntity');
  const drillDownId = searchParams.get('drillDownId');

  const isDrillDown = drillDownEntity && drillDownId;

  if (isDrillDown) {
    return <CostsGraphDrillDown />;
  }

  return <CostsGraphInner />;
}

export default CostsGraph;
