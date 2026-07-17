import useModals, { modals } from '@Src/hooks/use-modals';
import AddGroupToKey from './add-group-to-key';
import AddGroupsToRoute from './add-groups-to-route';
import AddKeysToGroups from './add-keys-to-group';
import AddRoutesToGroups from './add-routes-to-group';
import CreateAlertRule from './create-alert-rule';
import CreateGroup from './create-group';
import CreateKey from './create-key';
import CreateProject from './create-project';
import DeleteGroupWithAssociatedItems from './delete-group-with-associated-items';
import DeleteKeyWithGroups from './delete-key-with-groups';
import EditGroup from './edit-group';
import EditKey from './edit-key';
import EditProjectConfig from './edit-project-config';
import RouteAnalytics from './route-analytics';
import TraceDetail from './trace-detail';

export default function ModalsProvider() {
  const { modalPayload } = useModals();
  const modalName = modalPayload?.modalName;

  switch (modalName) {
    case modals.ADD_KEYS_TO_GROUP:
      return <AddKeysToGroups />;

    case modals.ADD_ROUTES_TO_GROUP:
      return <AddRoutesToGroups />;

    case modals.ADD_GROUP_TO_KEY:
      return <AddGroupToKey />;

    case modals.ADD_GROUPS_TO_ROUTE:
      return <AddGroupsToRoute />;

    case modals.CREATE_ALERT_RULE:
      return <CreateAlertRule />;

    case modals.CREATE_GROUPS:
      return <CreateGroup />;

    case modals.CREATE_KEY:
      return <CreateKey />;

    case modals.CREATE_PROJECT:
      return <CreateProject />;

    case modals.DELETE_KEY_WITH_GROUPS:
      return <DeleteKeyWithGroups />;

    case modals.DELETE_GROUP_WITH_ASSOCIATED_ITEMS:
      return <DeleteGroupWithAssociatedItems />;

    case modals.EDIT_GROUP:
      return <EditGroup />;

    case modals.EDIT_KEY:
      return <EditKey />;

    case modals.EDIT_PROJECT_CONFIG:
      return <EditProjectConfig />;

    case modals.ROUTE_ANALYTICS:
      return <RouteAnalytics />;

    case modals.TRACE_DETAIL:
      return <TraceDetail />;

    default:
      return false;
  }
}
