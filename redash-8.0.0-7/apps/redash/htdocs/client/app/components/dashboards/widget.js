import { filter } from 'lodash';
import { angular2react } from 'angular2react';
import template from './widget.html';
import TextboxDialog from '@/components/dashboards/TextboxDialog';
import widgetDialogTemplate from './widget-dialog.html';
import EditParameterMappingsDialog from '@/components/dashboards/EditParameterMappingsDialog';
import './widget.less';
import './widget-dialog.less';

const WidgetDialog = {
  template: widgetDialogTemplate,
  bindings: {
    resolve: '<',
    close: '&',
    dismiss: '&',
  },
  controller() {
    this.widget = this.resolve.widget;
  },
};

export let DashboardWidget = null; // eslint-disable-line import/no-mutable-exports

function DashboardWidgetCtrl($scope, $location, $uibModal, $window, $rootScope, $timeout, Events, currentUser) {
  this.isLoaded = false; // Initialize the loading state flag.
  this.canViewQuery = currentUser.hasPermission('view_query');

  // Initialize widget type early to prevent template errors
  if (!this.widget) {
    console.error('Widget is undefined in DashboardWidgetCtrl');
    this.type = 'restricted';
    this.isLoaded = true;
    return;
  }

  this.editTextBox = () => {
    TextboxDialog.showModal({
      dashboard: this.dashboard,
      text: this.widget.text,
      onConfirm: (text) => {
        this.widget.text = text;
        return this.widget.save();
      },
    });
  };

  this.expandVisualization = () => {
    $uibModal.open({
      component: 'widgetDialog',
      resolve: {
        widget: this.widget,
      },
      size: 'lg',
    });
  };

  this.hasParameters = () => this.widget.query.getParametersDefs().length > 0;

  this.editParameterMappings = () => {
    EditParameterMappingsDialog.showModal({
      dashboard: this.dashboard,
      widget: this.widget,
    }).result.then((valuesChanged) => {
      this.localParameters = null;

      if (valuesChanged) {
        $timeout(() => this.refresh());
      }
      $scope.$applyAsync();
      $rootScope.$broadcast('dashboard.update-parameters');
    });
  };

  this.localParametersDefs = () => {
    if (!this.localParameters) {
      this.localParameters = filter(
        this.widget.getParametersDefs(),
        param => !this.widget.isStaticParam(param),
      );
    }
    return this.localParameters;
  };

  this.deleteWidget = () => {
    if (!$window.confirm(`Are you sure you want to remove "${this.widget.getName()}" from the dashboard?`)) {
      return;
    }

    this.widget.delete().then(() => {
      if (this.deleted) {
        this.deleted({});
      }
    });
  };

  // Helper method to safely get query result
  this.getQueryResult = () => {
    try {
      if (!this.widget) return null;
      if (typeof this.widget.getQueryResult !== 'function') return null;
      return this.widget.getQueryResult();
    } catch (e) {
      console.error('Error getting query result:', e);
      return null;
    }
  };

  // Helper method to safely get query
  this.getQuery = () => {
    try {
      if (!this.widget) return null;
      if (typeof this.widget.getQuery !== 'function') return null;
      return this.widget.getQuery();
    } catch (e) {
      console.error('Error getting query:', e);
      return null;
    }
  };

  Events.record('view', 'widget', this.widget.id);

  this.load = (refresh = false) => {
    const maxAge = $location.search().maxAge;
    return this.widget.load(refresh, maxAge).then(() => {
      // Set the flag to true only after the promise resolves successfully.
      this.isLoaded = true;
    }).catch((error) => {
      // Mark as loaded even on error so the error state can be displayed
      this.isLoaded = true;
      console.error('Widget load error:', error);
      // Re-throw to allow error handling upstream if needed
      throw error;
    });
  };

  this.forceRefresh = () => this.load(true);

  this.refresh = (buttonId) => {
    this.refreshClickButtonId = buttonId;
    this.load(true).finally(() => {
      this.refreshClickButtonId = undefined;
    });
  };

  if (this.widget.visualization) {
    Events.record('view', 'query', this.widget.visualization.query.id, { dashboard: true });
    Events.record('view', 'visualization', this.widget.visualization.id, { dashboard: true });
    this.type = 'visualization';
    this.load();
  } else if (this.widget.restricted) {
    this.type = 'restricted';
    this.isLoaded = true; // Restricted widgets don't load data, so mark as loaded.
  } else {
    this.type = 'textbox';
    this.isLoaded = true; // Textbox widgets don't load data, so mark as loaded.
  }
}

const DashboardWidgetOptions = {
  template,
  controller: DashboardWidgetCtrl,
  bindings: {
    widget: '<',
    public: '<',
    dashboard: '<',
    filters: '<',
    deleted: '<',
  },
};

export default function init(ngModule) {
  ngModule.config(['$provide', ($provide) => {
    $provide.decorator('$exceptionHandler', ['$delegate', function($delegate) {
      return function(exception, cause) {
        console.error('[NG-EXCEPTION]', exception, cause);
        $delegate(exception, cause);
      };
    }]);
  }]);

  ngModule.component('widgetDialog', WidgetDialog);
  ngModule.component('dashboardWidget', DashboardWidgetOptions);
  ngModule.run(['$injector', ($injector) => {
    DashboardWidget = angular2react('dashboardWidget', DashboardWidgetOptions, $injector);
  }]);
}

init.init = true;
