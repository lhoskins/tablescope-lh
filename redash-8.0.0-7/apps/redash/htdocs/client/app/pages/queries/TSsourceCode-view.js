// client/app/pages/queries/TSsource-view.js
/* eslint-disable func-names */

import map from 'lodash/map';
import debounce from 'lodash/debounce';
// Point at the data-view template instead of the code template:
import template from './TSquery.html';
import EditParameterSettingsDialog from '@/components/EditParameterSettingsDialog';

// -----------------------------------------------------------------------------
// Controller
// -----------------------------------------------------------------------------
function QuerySourceCtrl(
  Events,
  $controller,
  $scope,
  $location,
  $uibModal,
  currentUser,
  KeyboardShortcuts,
  $rootScope,
) {
  'ngInject';

  // TS Workspace helper stubs – satisfy TSQueryEditorCode props
  if (!$scope.listenForResize) {
    $scope.listenForResize = fn => ($scope.$parent || $scope).$on('angular-resizable.resizing', fn);
  }
  if (!$scope.listenForEditorCommand) {
    $scope.listenForEditorCommand = fn => $scope.$on('query-editor.command', fn);
  }

  // Re-use everything TSQueryViewCtrl sets up
  $controller('TSQueryViewCtrl', { $scope });

  Events.record('view_source', 'query', $scope.query.id);

  const isNewQuery = !$scope.query.id;
  let persistedQueryText = $scope.query.query;

  // ---------------------------------------------------------------------------
  // Scope flags
  // ---------------------------------------------------------------------------
  $scope.sourceMode = true; // show the editor region
  $scope.isDirty = false;
  $scope.base_url = `${$location.protocol()}://${$location.host()}:${$location.port()}`;
  $scope.modKey = KeyboardShortcuts.modKey;

  // When dataset finished & status=done we still show results:
  Object.defineProperty($scope, 'showDataset', {
    get() {
      return $scope.queryResult && $scope.queryResult.getStatus() === 'done';
    },
  });

  // ---------------------------------------------------------------------------
  // Keyboard shortcuts
  // ---------------------------------------------------------------------------
  const shortcuts = {
    'mod+s': () => {
      if ($scope.canEdit) $scope.saveQuery();
    },
    'mod+p': () => {
      $scope.addNewParameter();
    },
  };
  KeyboardShortcuts.bind(shortcuts);
  $scope.$on('$destroy', () => KeyboardShortcuts.unbind(shortcuts));

  // Enable/disable “Fork” menu item
  $scope.canForkQuery = () => currentUser.hasPermission('edit_query') && !$scope.dataSource.view_only;

  // Keep $scope.query up-to-date while the user types
  $scope.updateQuery = debounce((newText) => {
    $scope.$apply(() => {
      $scope.query.query = newText;
    });
  }, 200);

  // ---------------------------------------------------------------------------
  // Save query (override parent implementation to track dirty flag + redirect)
  // ---------------------------------------------------------------------------
  const parentSaveQuery = $scope.saveQuery;
  $scope.saveQuery = (options, data) => {
    const p = parentSaveQuery(options, data);

    p.then((saved) => {
      persistedQueryText = saved.query;
      $scope.isDirty = $scope.query.query !== persistedQueryText;
      $scope.query.version = saved.version; // refresh version

      if (isNewQuery) {
        // First save of a new query → redirect to /source URL that has ID
        $location.path(saved.getSourceLink());
      }
    });

    return p;
  };

  // ---------------------------------------------------------------------------
  // Parameter helpers
  // ---------------------------------------------------------------------------
  $scope.addNewParameter = () => {
    EditParameterSettingsDialog.showModal({
      parameter: { title: null, name: '', type: 'text', value: null },
      existingParams: map($scope.query.getParameters().get(), p => p.name),
    }).result.then((param) => {
      const p = $scope.query.getParameters().add(param);
      $rootScope.$broadcast('query-editor.command', 'paste', p.toQueryTextFragment());
      $rootScope.$broadcast('query-editor.command', 'focus');
    });
  };

  // Auto-save when parameters panel changes and the query isn’t dirty
  $scope.onParametersUpdated = () => {
    if (!$scope.isDirty) $scope.saveQuery();
  };

  // Track dirty state
  $scope.$watch('query.query', (newText) => {
    $scope.isDirty = newText !== persistedQueryText;
  });
}

// -----------------------------------------------------------------------------
// Routes
// -----------------------------------------------------------------------------
export default function init(ngModule) {
  ngModule.controller('QuerySourceCtrl', QuerySourceCtrl);

  return {
    '/tcqueries/new': {
      template,
      layout: 'fixed',
      controller: 'QuerySourceCtrl',
      reloadOnSearch: false,
      resolve: {
        query: (Query) => {
          'ngInject';

          return Query.newQuery();
        },
        dataSources: (DataSource) => {
          'ngInject';

          return DataSource.query().$promise;
        },
      },
    },

    '/tcqueries/:queryId/source': {
      template,
      layout: 'fixed',
      controller: 'QuerySourceCtrl',
      reloadOnSearch: false,
      resolve: {
        query: (Query, $route) => {
          'ngInject';

          return Query.get({ id: $route.current.params.queryId }).$promise;
        },
      },
    },
  };
}

init.init = true;
