/* eslint-disable */

import { pick, some, find, minBy, map, intersection, isArray, omit } from 'lodash';
import { SCHEMA_NOT_SUPPORTED, SCHEMA_LOAD_ERROR } from '@/services/data-source';
import getTags from '@/services/getTags';
import { policy } from '@/services/policy';
import { Visualization } from '@/services/visualization';
import Notifications from '@/services/notifications';
import ScheduleDialog from '@/components/queries/ScheduleDialog';
import { newVisualization } from '@/visualizations';
import EditVisualizationDialog from '@/visualizations/EditVisualizationDialog';
import EmbedQueryDialog from '@/components/queries/EmbedQueryDialog';
import notification from '@/services/notification';
import tsqueryTemplate from './TSquery.html';

/* ───────────────────────────────────────────────────────────────
   PATCH – helpers return either:
            ""          → rd-tab adds its own  #<visId>
         or "#<frag>"   → already has desired fragment
   +  hash-cleaner: after Angular consumes the fragment,
      it’s removed so only “…/TShome” remains visible.
──────────────────────────────────────────────────────────────── */
(function patchQueryLinks() {
  if (window.__tsQueriesPatched) return;
  window.__tsQueriesPatched = true;

  /* ------------------------------------------------------
     1️⃣  Wrap all helpers so they return relative / hash-only
  ------------------------------------------------------ */
  const waitForInjector = () => {
    const injector = window.angular?.element(document.body).injector?.();
    if (!injector) return setTimeout(waitForInjector, 50);

    const Query = injector.get('Query');
    const Viz   = Visualization; // imported class (not from DI)

    const toRelative = (url) => {
      if (typeof url !== 'string') return url;
      url = url.replace(/(^|\/)queries\//, '$1tsqueries/'); // keep internal consistency

      // keep only existing fragment, else blank (rd-tab will append "#<vis.id>")
      return url.includes('#') ? `#${url.split('#').pop()}` : '';
    };

    const wrap = (proto, fn) => {
      const orig = proto[fn];
      if (typeof orig !== 'function') return;
      proto[fn] = function patched(...args) {
        return toRelative(orig.apply(this, args));
      };
    };

    wrap(Query.prototype, 'getUrl');
    wrap(Query.prototype, 'getSourceLink');
    if (Viz?.prototype?.getLink) wrap(Viz.prototype, 'getLink');

    /* eslint-disable no-console */
    console.log('[TSview] link helpers patched (relative/hash-only)');
    /* eslint-enable  no-console */
  };
  waitForInjector();

  /* ------------------------------------------------------
     2️⃣  Hash-cleaner → keep address bar at “…/TShome”
  ------------------------------------------------------ */
  const TSHOME_BASE = location.pathname; // we’re already on “…/TShome”

  /** Remove the fragment once Angular has reacted to it. */
  const clearHash = () => {
    if (!location.hash) return;                    // nothing to clear
    const frag = location.hash;
    // Delay a tick so rd-tab / Angular digest sees it first
    setTimeout(() => {
      if (location.hash === frag) {                // still the same? wipe it
        history.replaceState(null, '', TSHOME_BASE);
      }
    }, 0);
  };

  window.addEventListener('hashchange', clearHash);
  clearHash(); // in case a fragment sneaks in on initial load
})();
/* ───────────────────────────────────────────────────────────────*/


function QueryViewCtrl(
  $scope,
  Events,
  $route,
  $routeParams,
  $location,
  $window,
  $q,
  KeyboardShortcuts,
  Title,
  AlertDialog,
  clientConfig,
  $uibModal,
  currentUser,
  Query,
  DataSource,
  $document,
  $interval,
  $rootScope
) {
  'ngInject';
  console.log('%c[TSview] QueryViewCtrl boot (queryId: ' + $routeParams.queryId + ')', 'color: #0a0; font-weight: bold;', $location.path());

  // ───────────────────────────────────────────────────────────────
  // NEW: more flexible, case-insensitive extractor + logs
  function detectSourceTable(sqlText = '') {
    const regex = /\bfrom\s+[`"'[\]]*([A-Za-z0-9_.]+)[`"'[\]]*/i;
    console.log('TSview.detectSourceTable input:', sqlText);
    const match = regex.exec(sqlText);
    console.log('TSview.detectSourceTable match:', match);
    return match ? match[1] : null;
  }
  // ───────────────────────────────────────────────────────────────

  // Should create it here since visualization registry might not be fulfilled when this file is loaded
  const DEFAULT_VISUALIZATION = newVisualization('MUI_DATA_GRID', { itemsPerPage: 50, name: 'Table' });

  function getQueryResult(maxAge, selectedQueryText) {
    console.log('[TSview.getQueryResult] maxAge', maxAge, 'dirty', $scope.isDirty, 'selTxt len', ($scope.selectedQueryText||'').length);

    // AGGRESSIVE FIX: ALWAYS force fresh execution (maxAge=0) to prevent stale cached results
    // This ensures business-critical accuracy by never showing outdated data
    console.log('[TSview.getQueryResult] FORCING maxAge=0 for fresh execution (was:', maxAge, ')');
    maxAge = 0;
    
    // Original logic kept for reference but overridden above
    // if (maxAge === undefined) {
    //   maxAge = $location.search().maxAge;
    // }
    // if (maxAge === undefined) {
    //   maxAge = -1;
    // }
    $scope.showLog = false;

/* ──────────── Drill‑down Scope Panel State ──────────── */
$scope.drilldownMode = false;
$scope.scopeInfo = null;
$scope.scopeCollapsed = true;
$scope.canEditName = () => $scope.canEdit && !$scope.drilldownMode;

// Handle drill‑down activation dispatched from React grid
const __ts_drill_handler = (ev) => {
  console.log("[TSview] drilldown-activated caught:", ev.detail);
  const info = ev.detail || {};
  $scope.$applyAsync(() => {
    $scope.drilldownMode = true;
    $scope.scopeInfo = info;
    $scope.scopeCollapsed = false;
  });
};
document.addEventListener('drilldown-activated', __ts_drill_handler);

// Clean up listener when this view is destroyed
$scope.$on('$destroy', () => {
  document.removeEventListener('drilldown-activated', __ts_drill_handler);
});

// Reset drill‑down mode when the user navigates away
$rootScope.$on('$routeChangeStart', () => {
  $scope.drilldownMode = false;
  $scope.scopeInfo = null;
  $scope.scopeCollapsed = true;
});
/* ───────────────────────────────────────────────────────── */
    if ($scope.isDirty) {
      $scope.queryResult = $scope.query.getQueryResultByText(maxAge, selectedQueryText);
    } else {
      $scope.queryResult = $scope.query.getQueryResult(maxAge);
    }
  }

  function getDataSourceId() {
    let dataSourceId = $scope.query.data_source_id;
    if (dataSourceId === undefined) {
      dataSourceId = parseInt(localStorage.lastSelectedDataSourceId, 10);
    }
    const isValidDataSourceId = !Number.isNaN(dataSourceId) && some($scope.dataSources, ds => ds.id === dataSourceId);
    if (!isValidDataSourceId) {
      dataSourceId = $scope.dataSources[0].id;
    }
    return dataSourceId;
  }

  function getSchema(refresh = undefined) {
    $scope.schema = [];
    $scope.dataSource.getSchema(refresh).then((data) => {
      if (data.schema) {
        $scope.schema = data.schema;
        $scope.schema.forEach((table) => {
          table.collapsed = true;
        });
      } else if (data.error.code === SCHEMA_NOT_SUPPORTED) {
        $scope.schema = undefined;
      } else if (data.error.code === SCHEMA_LOAD_ERROR) {
        notification.error('Schema refresh failed.', 'Please try again later.');
      } else {
        notification.error('Schema refresh failed.', 'Please try again later.');
      }
    });
  }

  $scope.refreshSchema = () => getSchema(true);

  function updateDataSources(dataSources) {
    function canUseDataSource(dataSource) {
      return !dataSource.view_only || dataSource.id === $scope.query.data_source_id;
    }
    $scope.dataSources = dataSources.filter(canUseDataSource);
    if ($scope.dataSources.length === 0) {
      $scope.noDataSources = true;
      return;
    }
    if ($scope.query.isNew()) {
      $scope.query.data_source_id = getDataSourceId();
    }
    $scope.dataSource = find(dataSources, ds => ds.id === $scope.query.data_source_id);
    $scope.canCreateQuery = some(dataSources, ds => !ds.view_only);
    getSchema();
  }

  $scope.updateSelectedQuery = (selectedQueryText) => {
    $scope.selectedQueryText = selectedQueryText;
  };

  $scope.executeQuery = () => {
    console.log('[TSview.executeQuery] isDirty=', $scope.isDirty, ' selTxt len=', ($scope.selectedQueryText||'').length);

    if (!$scope.canExecuteQuery()) {
      return;
    }
    if (!$scope.query.query) {
      return;
    }
    getQueryResult(0, $scope.selectedQueryText);
    $scope.lockButton(true);
    $scope.cancelling = false;
    Events.record('execute', 'query', $scope.query.id);
    Notifications.getPermissions();
  };

  $scope.currentUser = currentUser;
  $scope.dataSource = {};
  // Initial assignment of query from route resolve
  $scope.query = $route.current.locals.query;
  Title.set($scope.query.name);
  console.log('%c[TSview] QueryViewCtrl initial load - Query Name: ' + $scope.query.name + ' (ID: ' + $scope.query.id + ')', 'color: #008; font-weight: bold;');


  // Watch for changes in queryId from route parameters and update the query object.
  // This handles cases where the route resolves might not re-run or the controller
  // is not re-instantiated on subsequent drill-downs that change the queryId.
  $scope.$watch(
    () => $routeParams.queryId,
    (newQueryId, oldQueryId) => {
      console.log(`%c[TSview] $routeParams.queryId changed detected: OLD=${oldQueryId} -> NEW=${newQueryId}`, 'color: #00f; font-weight: bold;');
      if (newQueryId && newQueryId !== oldQueryId) {
        console.log(`%c[TSview] Fetching new query for ID: ${newQueryId}`, 'color: #00f;');
        // Fetch the new query data
        Query.get({ id: newQueryId }).$promise.then(
          (newQuery) => {
            console.log(`%c[TSview] New query fetched successfully! ID: ${newQuery.id}, Name: ${newQuery.name}`, 'color: #0a0;');
            $scope.query = newQuery; // Update the query object on scope
            Title.set($scope.query.name); // Update page title
            console.log(`%c[TSview] Page Title updated to: ${$scope.query.name}`, 'color: #0a0;');

            // Re-evaluate query-related properties, like isQueryOwner, canEdit etc.
            $scope.isQueryOwner = currentUser.id === $scope.query.user.id || currentUser.hasPermission('admin');
            
            // Use ONLY backend can_edit flag - backend enforces RBAC rules correctly
            $scope.canEdit = $scope.query.can_edit || false;
            console.log('[TSview] canEdit from backend (query changed):', {
              'currentUser.id': currentUser.id,
              'query.user_id': $scope.query.user_id,
              'query.can_edit': $scope.query.can_edit,
              'final canEdit': $scope.canEdit
            });
            $scope.queryResult = null; // Clear previous result to trigger new execution if needed
            console.log('[TSview] Query ID changed - forcing fresh execution with maxAge=0');
            getQueryResult(0); // Force fresh execution to ensure results match current query
          },
          (error) => {
            console.error('[TSview] Failed to load new query on ID change:', error);
            notification.error('Failed to load query.', 'Please try again.');
          }
        );
      } else if (newQueryId && newQueryId === oldQueryId) {
        console.log(`%c[TSview] $routeParams.queryId changed, but new ID is same as old. Current Query Name: ${$scope.query.name}`, 'color: #f80;');
      } else {
        console.log('%c[TSview] $routeParams.queryId did not change or is null/undefined.', 'color: #f00;');
      }
    }
  );
  // ──────────────────────────────────────────────────────────────────────────

  $scope.showPermissionsControl = clientConfig.showPermissionsControl;

  $scope.$watch('selectedVisualization', () => {
    if ($scope.selectedVisualization) {
      $scope.selectedTab = $scope.selectedVisualization.id;
    }
  });

  const shortcuts = {
    'mod+enter': $scope.executeQuery,
    'alt+enter': $scope.executeQuery,
  };
  KeyboardShortcuts.bind(shortcuts);

  // AGGRESSIVE FIX: Use polling on a global variable and broadcast an event on the rootScope
  console.log('[TSview | AGGRESSIVE FIX v2] Starting polling interval to check for `window.__drilldownQueryName`.');
  const pollingInterval = $interval(() => {
    if ($window.__drilldownQueryName) {
      const newName = $window.__drilldownQueryName;
      console.log(`[TSview | Polling] Detected change on global. Broadcasting 'drilldown-name-updated' with name: "${newName}"`);
      // Use rootScope to broadcast an event that the local scope can listen for
      $rootScope.$broadcast('drilldown-name-updated', newName);
      // Clear the global variable so we don't process it again
      $window.__drilldownQueryName = null;
    }
  }, 250);

  const drilldownListener = $scope.$on('drilldown-name-updated', (event, newName) => {
    console.log(`[TSview | Event Listener] Caught 'drilldown-name-updated'. Old name: "${$scope.query.name}", New name: "${newName}"`);
    if ($scope.query.name !== newName) {
      $scope.query.name = newName;
      // No need for $apply or $applyAsync here because $interval and $broadcast handle the digest cycle
      console.log(`[TSview | Event Listener] Scope updated. Current name: "${$scope.query.name}"`);
    }
  });

  $scope.$on('$destroy', () => {
    KeyboardShortcuts.unbind(shortcuts);
    // Clean up both the interval and the event listener
    console.log('[TSview | AGGRESSIVE FIX v2] Destroying component. Clearing polling interval and event listener.');
    $interval.cancel(pollingInterval);
    drilldownListener(); // Deregister the listener
  });

  // Always force fresh execution on page load to ensure results match current query
  // This prevents showing stale cached results when query has been modified
  console.log('[TSview] Page load - checking if query needs execution:', {
    hasResult: $scope.query.hasResult(),
    paramsRequired: $scope.query.paramsRequired(),
    latest_query_data_id: $scope.query.latest_query_data_id,
    query_length: $scope.query.query?.length
  });
  
  if ($scope.query.hasResult() || $scope.query.paramsRequired()) {
    console.log('[TSview] Query has results or requires params - forcing fresh execution (maxAge=0)');
    getQueryResult(0); // maxAge=0 forces fresh execution
  } else {
    console.log('[TSview] Query has NO results and NO params required - skipping execution');
  }
  $scope.queryExecuting = false;
  $scope.isQueryOwner = currentUser.id === $scope.query.user.id || currentUser.hasPermission('admin');
  
  // Use ONLY backend can_edit flag - backend enforces RBAC rules correctly
  $scope.canEdit = $scope.query.can_edit || false;
  console.log('[TSview] canEdit from backend:', {
    'currentUser.id': currentUser.id,
    'query.user_id': $scope.query.user_id,
    'query.can_edit': $scope.query.can_edit,
    'final canEdit': $scope.canEdit
  });
  $scope.canViewSource = currentUser.hasPermission('view_source');

  $scope.canExecuteQuery = () => !$scope.query.$parameters.hasPendingValues() &&
    ($scope.query.is_safe || (currentUser.hasPermission('execute_query') && !$scope.dataSource.view_only));

  $scope.canForkQuery = () => currentUser.hasPermission('edit_query') && !$scope.dataSource.view_only;
  $scope.canScheduleQuery = () => currentUser.hasPermission('schedule_query');

  if ($route.current.locals.dataSources) {
    $scope.dataSources = $route.current.locals.dataSources;
    updateDataSources($route.current.locals.dataSources);
  } else {
    $scope.dataSources = DataSource.query(updateDataSources);
  }

  // ─────────────────────────────────────────────────────────────
  // TS Workspace helpers – satisfy TSQueryEditor’s required props
  if (!$scope.listenForResize) {
    // forward “angular-resizable” events from any parent row
    $scope.listenForResize = fn => ($scope.$parent || $scope).$on('angular-resizable.resizing', fn);
  }
  if (!$scope.listenForEditorCommand) {
    // forward custom commands that TSQueryEditor sends itself
    $scope.listenForEditorCommand = fn => $scope.$on('query-editor.command', fn);
  }
  // ─────────────────────────────────────────────────────────────

  $scope.showDataset = true;
  $scope.showLog = false;

  $scope.lockButton = (lock) => {
    $scope.queryExecuting = lock;
  };

  $scope.showApiKey = () => {
    $uibModal.open({
      component: 'apiKeyDialog',
      resolve: {
        query: $scope.query,
      },
    });
  };

  $scope.duplicateQuery = () => {
    const tabName = `duplicatedQueryTab${Math.random().toString()}`;
    $window.open('', tabName);
    Query.fork({ id: $scope.query.id }, (newQuery) => {
      const queryUrl = newQuery.getUrl(true);
      $window.open(queryUrl, tabName);
    });
  };

  $scope.saveTags = (tags) => {
    $scope.query.tags = tags;
    $scope.saveQuery({}, { tags: $scope.query.tags });
  };

  $scope.loadTags = () => getTags('api/queries/tags').then(tags => map(tags, t => t.name));
  $scope.applyParametersChanges = () => {
    $scope.$apply();
  };

  /* --- next chunk continues with saveQuery and beyond --- */
  $scope.saveQuery = (customOptions, data) => {
    let request = data;
    if (request) {
      if ($scope.query.isNew()) {
        return $q.reject();
      }
      request.id = $scope.query.id;
      request.version = $scope.query.version;
    } else {
      request = pick($scope.query, [
        'schedule',
        'query',
        'id',
        'description',
        'name',
        'data_source_id',
        'options',
        'latest_query_data_id',
        'version',
        'is_draft',
      ]);
    }
    const options = Object.assign(
      {},
      {
        successMessage: 'Query saved',
        errorMessage: 'Query could not be saved',
      },
      customOptions,
    );
    if (options.force) {
      delete request.version;
    }
    if (request.options && request.options.parameters) {
      request.options = {
        ...request.options,
        parameters: map(request.options.parameters, p => omit(p, 'pendingValue')),
      };
    }
    function overwrite() {
      options.force = true;
      $scope.saveQuery(options, data);
    }
    return Query.save(
      request,
      (updatedQuery) => {
        notification.success(options.successMessage);
        $scope.query.version = updatedQuery.version;
      },
      (error) => {
        if (error.status === 409) {
          const errorMessage = 'It seems like the query has been modified by another user.';
          if ($scope.isQueryOwner) {
            const title = 'Overwrite Query';
            const message = errorMessage + '<br>Are you sure you want to overwrite the query with your version?';
            const confirm = { class: 'btn-warning', title: 'Overwrite' };
            AlertDialog.open(title, message, confirm).then(overwrite);
          } else {
            notification.error(
              'Changes not saved',
              errorMessage + ' Please copy/backup your changes and reload this page.',
              { duration: null },
            );
          }
        } else {
          notification.error(options.errorMessage);
        }
      },
    ).$promise;
  };

  $scope.togglePublished = () => {
    Events.record('toggle_published', 'query', $scope.query.id);
    $scope.query.is_draft = !$scope.query.is_draft;
    $scope.saveQuery(undefined, { is_draft: $scope.query.is_draft });
  };

  $scope.saveDescription = (desc) => {
    $scope.query.description = desc;
    Events.record('edit_description', 'query', $scope.query.id);
    $scope.saveQuery(undefined, { description: $scope.query.description });
  };

  $scope.saveName = (name) => {
    $scope.query.name = name;
    Events.record('edit_name', 'query', $scope.query.id);
    let customOptions;
    if ($scope.query.is_draft && clientConfig.autoPublishNamedQueries && $scope.query.name !== 'New Query') {
      $scope.query.is_draft = false;
      customOptions = {
        successMessage: 'Query saved and published',
      };
    }
    $scope.saveQuery(customOptions, { name: $scope.query.name, is_draft: $scope.query.is_draft });
  };

  $scope.cancelExecution = () => {
    $scope.cancelling = true;
    $scope.queryResult.cancelExecution();
    Events.record('cancel_execute', 'query', $scope.query.id);
  };

  $scope.archiveQuery = () => {
    function archive() {
      Query.delete(
        { id: $scope.query.id },
        () => {
          $scope.query.is_archived = true;
          $scope.query.schedule = null;
        },
        () => {
          notification.error('Query could not be archived.');
        },
      );
    }
    const title = 'Archive Query';
    const message =
      'Are you sure you want to archive this query?<br/> All alerts and dashboard widgets created with its visualizations will be deleted.';
    const confirm = { class: 'btn-warning', title: 'Archive' };
    AlertDialog.open(title, message, confirm).then(archive);
  };

  $scope.updateDataSource = () => {
    Events.record('update_data_source', 'query', $scope.query.id);
    localStorage.lastSelectedDataSourceId = $scope.query.data_source_id;
    $scope.query.latest_query_data = null;
    $scope.query.latest_query_data_id = null;
    if ($scope.query.id) {
      Query.save(
        {
          id: $scope.query.id,
          data_source_id: $scope.query.data_source_id,
          latest_query_data_id: null,
        },
        (updatedQuery) => {
          $scope.query.version = updatedQuery.version;
        },
      );
    }
    $scope.dataSource = find($scope.dataSources, ds => ds.id === $scope.query.data_source_id);
    getSchema();
    $scope.executeQuery();
  };

  $scope.setVisualizationTab = (visualization) => {
    $scope.selectedVisualization = visualization;
    if (visualization) {
      $location.hash(visualization.id);
    }
  };

  $scope.deleteVisualization = ($e, vis) => {
    $e.preventDefault();
    const title = undefined;
    const message = `Are you sure you want to delete ${vis.name} ?`;
    const confirm = { class: 'btn-danger', title: 'Delete' };
    AlertDialog.open(title, message, confirm).then(() => {
      Visualization.delete(
        { id: vis.id },
        () => {
          if ($scope.selectedVisualization.id === vis.id) {
            const muiGrid = find($scope.query.visualizations, v => v.type === 'MUI_DATA_GRID');
            $scope.setVisualizationTab(muiGrid || DEFAULT_VISUALIZATION);
          }
          $scope.query.visualizations =
            $scope.query.visualizations.filter(v => vis.id !== v.id);
        },
        () => {
          notification.error(
            'Error deleting visualization.',
            "Maybe it's used in a dashboard?"
          );
        },
      );
    });
  };

  $scope.$watch('query.name', () => {
    Title.set($scope.query.name);
  });

  /* --- next chunk continues with status watch and init export --- */
  $scope.$watch('queryResult && queryResult.getStatus()', (status) => {
    if (!status) {
      return;
    }
    if (status === 'done') {
      const ranSelectedQuery = $scope.query.query !== $scope.queryResult.query_result.query;
      if (!ranSelectedQuery) {
        $scope.query.latest_query_data_id = $scope.queryResult.getId();
        $scope.query.queryResult = $scope.queryResult;
      }
      Notifications.showNotification('Redash', `${$scope.query.name} updated.`);

      // ───────────────────────── NEW – BEGIN ─────────────────────────
      const tbl = detectSourceTable($scope.query.query);
      console.log('TSview after run, detected table:', tbl);
      const safeTbl =
        tbl ||
        ($scope.schema && $scope.schema[0] && $scope.schema[0].name);
      console.log('TSview using safeTbl:', safeTbl);
      if (safeTbl) {
        window.__currentSourceTable = safeTbl; // for first-mount
        document.dispatchEvent(
          new CustomEvent('source-table-detected', {
            detail: { tableName: safeTbl },
          }),
        );
      }
      // ───────────────────────── NEW – END ──────────────────────────
    } else if (status === 'failed') {
      Notifications.showNotification(
        'Redash',
        `${$scope.query.name} failed to run: ${$scope.queryResult.getError()}`
      );
    }
    if (status === 'done' || status === 'failed') {
      $scope.lockButton(false);
    }
    if ($scope.queryResult.getLog() != null) {
      $scope.showLog = true;
    }
  });

  function getVisualization(visId) {
    return find($scope.query.visualizations, item => item.id === visId);
  }

  $scope.openVisualizationEditor = (visId) => {
    function openModal() {
      EditVisualizationDialog.showModal({
        query: $scope.query,
        visualization: getVisualization(visId),
        queryResult: $scope.queryResult,
      }).result.then((visualization) => {
        $scope.setVisualizationTab(visualization);
        $scope.$applyAsync();
      });
    }
    if ($scope.query.isNew()) {
      $scope.saveQuery().then((query) => {
        $location.path(query.getSourceLink()).hash('add');
      });
    } else {
      openModal();
    }
  };

  if ($location.hash() === 'add') {
    $location.hash(null);
    $scope.openVisualizationEditor();
  }

  const intervals = clientConfig.queryRefreshIntervals;
  const allowedIntervals = policy.getQueryRefreshIntervals();
  $scope.refreshOptions = isArray(allowedIntervals)
    ? intersection(intervals, allowedIntervals)
    : intervals;

  $scope.showScheduleForm = false;
  $scope.editSchedule = () => {
    if (!$scope.canEdit || !$scope.canScheduleQuery) {
      return;
    }
    ScheduleDialog.showModal({
      schedule: $scope.query.schedule,
      refreshOptions: $scope.refreshOptions,
    }).result.then((schedule) => {
      $scope.query.schedule = schedule;
      $scope.saveQuery();
    });
  };

  $scope.closeScheduleForm = () => {
    $scope.$apply(() => {
      $scope.showScheduleForm = false;
    });
  };

  $scope.openAddToDashboardForm = (visId) => {
    const visualization = getVisualization(visId);
    $uibModal.open({
      component: 'addToDashboardDialog',
      size: 'sm',
      resolve: {
        query: $scope.query,
        vis: visualization,
      },
    });
  };

  $scope.showEmbedDialog = (query, visId) => {
    const visualization = getVisualization(visId);
    EmbedQueryDialog.showModal({ query, visualization });
  };

  // Watcher for subsequent navigation by URL hash
  $scope.$watch(
    () => $location.hash(),
    (hash) => {
      if (hash) {
        const visId = hash.substring(1); // remove '#'
        if (visId && (!$scope.selectedVisualization || $scope.selectedVisualization.id != visId)) {
            const visFromHash = find($scope.query.visualizations, vis => String(vis.id) === visId);
            if (visFromHash) {
                $scope.selectedVisualization = visFromHash;
            }
        }
      }
    }
  );


  $scope.showManagePermissionsModal = () => {
    $uibModal.open({
      component: 'permissionsEditor',
      resolve: {
        aclUrl: { url: `api/queries/${$routeParams.queryId}/acl` },
        owner: $scope.query.user,
      },
    });
  };
}

export default function init(ngModule) {
  ngModule.controller('TSQueryViewCtrl', QueryViewCtrl);
  return {
    // Existing route for saved queries by ID:
    '/tsqueries/:queryId': {
      template: tsqueryTemplate,
      layout: 'fixed',
      controller: 'TSQueryViewCtrl',
      reloadOnSearch: false,
      resolve: {
        // existing behavior: load query from backend by ID
        query: (Query, $route) => {
          'ngInject';
          return Query.get({ id: $route.current.params.queryId }).$promise;
        },
        // (optionally) preload data sources list
        dataSources: (DataSource) => {
          'ngInject';
          return DataSource.query().$promise;
        },
      },
    },
  };
}