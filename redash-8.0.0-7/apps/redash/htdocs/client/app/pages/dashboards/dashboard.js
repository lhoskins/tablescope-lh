import * as _ from 'lodash';
import PromiseRejectionError from '@/lib/promise-rejection-error';
import getTags from '@/services/getTags';
import { policy } from '@/services/policy';
import {
  editableMappingsToParameterMappings,
  synchronizeWidgetTitles,
} from '@/components/ParameterMappingInput';
import { collectDashboardFilters } from '@/services/dashboard';
import { durationHumanize } from '@/filters';
import template from './dashboard.html';
import ShareDashboardDialog from './ShareDashboardDialog';
import AddWidgetDialog from '@/components/dashboards/AddWidgetDialog';
import TextboxDialog from '@/components/dashboards/TextboxDialog';
import notification from '@/services/notification';

// Import the React-based EditProjectsDialog component.
import EditProjectsDialog from '@/components/EditProjectsDialog';

const orgSlug = window.location.pathname.split('/')[1] || 'default';

function getChangedPositions(widgets, nextPositions = {}) {
  return _.pickBy(nextPositions, (nextPos, widgetId) => {
    const widget = _.find(widgets, { id: Number(widgetId) });
    const prevPos = widget.options.position;
    return !_.isMatch(prevPos, nextPos);
  });
}

function DashboardCtrl(
  $routeParams,
  $location,
  $timeout,
  $q,
  $uibModal,
  $scope,
  $http, // Injected $http service
  Title,
  AlertDialog,
  Dashboard,
  currentUser,
  clientConfig,
  Events,
) {
  this.__tmplProbe = (name) => { console.log('[TMPL] loaded', name); };
  let recentPositions = {};

  const saveDashboardLayout = function saveDashboardLayout(changedPositions) {
    if (!this.dashboard.canEdit()) {
      return;
    }
    this.saveInProgress = true;
    const saveChangedWidgets = _.map(changedPositions, (position, id) => {
      const widget = _.find(this.dashboard.widgets, { id: Number(id) });
      if (!widget) {
        return Promise.resolve();
      }
      return widget.save('options', { position });
    });
    return $q
      .all(saveChangedWidgets)
      .then(() => {
        this.isLayoutDirty = false;
        if (this.editBtnClickedWhileSaving) {
          this.layoutEditing = false;
        }
      })
      .catch(() => {
        notification.error('Error saving changes.');
      })
      .finally(() => {
        this.saveInProgress = false;
        this.editBtnClickedWhileSaving = false;
        $scope.$applyAsync();
      });
  }.bind(this);

  const saveDashboardLayoutDebounced = _.debounce(function saveDashboardLayoutDebounced(...args) {
    this.saveDelay = true;
    saveDashboardLayout(...args);
    this.saveDelay = false;
  }.bind(this), 2000);


  this.retrySaveDashboardLayout = function retrySaveDashboardLayout() {
    this.onLayoutChange(recentPositions);
  };

  // grid vars
  this.saveDelay = false;
  this.saveInProgress = false;
  this.recentLayoutPositions = {};
  this.editBtnClickedWhileSaving = false;
  this.layoutEditing = false;
  this.isLayoutDirty = false;
  this.isGridDisabled = false;

  // dashboard vars
  this.isFullscreen = false;
  this.refreshRate = null;
  this.showPermissionsControl = clientConfig.showPermissionsControl;
  this.globalParameters = [];
  this.isDashboardOwner = false;
  this.filters = [];

  this.refreshRates = clientConfig.dashboardRefreshIntervals.map(interval => ({
    name: durationHumanize(interval),
    rate: interval,
    enabled: true,
  }));

  const allowedIntervals = policy.getDashboardRefreshIntervals();
  if (_.isArray(allowedIntervals)) {
    _.each(this.refreshRates, (rate) => {
      rate.enabled = allowedIntervals.indexOf(rate.rate) >= 0;
    });
  }

  this.setRefreshRate = function setRefreshRate(rate, load = true) {
    this.refreshRate = rate;
    if (rate !== null) {
      if (load) {
        this.refreshDashboard();
      }
      this.autoRefresh();
    }
  }.bind(this);

  this.extractGlobalParameters = function extractGlobalParameters() {
    this.globalParameters = this.dashboard.getParametersDefs();
  }.bind(this);

  $scope.$on('dashboard.update-parameters', () => {
    this.extractGlobalParameters();
  });

  const collectFilters = function collectFilters(dashboard, forceRefresh, updatedParameters = []) {
    const affectedWidgets = updatedParameters.length > 0 ? this.dashboard.widgets.filter(widget => Object.values(widget.getParameterMappings()).filter(mapping => mapping.type === 'dashboard-level').some(mapping => _.includes(updatedParameters.map(p => p.name), mapping.mapTo))) : this.dashboard.widgets;
    const queryResultPromises = _.compact(affectedWidgets.map((widget) => {
      widget.getParametersDefs();
      return widget.load(forceRefresh);
    }));
    return $q.all(queryResultPromises).then((queryResults) => {
      this.filters = collectDashboardFilters(dashboard, queryResults, $location.search());
      this.filtersOnChange = function (filters) {
        this.filters = filters;
        $scope.$applyAsync();
      }.bind(this);
    });
  }.bind(this);

  const renderDashboard = function renderDashboard(dashboard, force) {
    Title.set(dashboard.name);
    this.extractGlobalParameters();
    collectFilters(dashboard, force);
  }.bind(this);

  this.loadDashboard = _.throttle((force) => {
    Dashboard.get(
      { slug: $routeParams.dashboardSlug },
      (dashboard) => {
        this.dashboard = dashboard;
        // This is part of the projects feature, we keep it for display purposes
        $http.get(`/${orgSlug}/api/dashboards/${this.dashboard.id}`).then((response) => {
          const { data } = response;
          this.dashboard.project_id = data.project_id || [];
        });

        this.isDashboardOwner = currentUser.id === dashboard.user.id || currentUser.hasPermission('admin');
        Events.record('view', 'dashboard', dashboard.id);
        renderDashboard(dashboard, force);

        if ($location.search().edit === true) {
          $location.search('edit', null);
          this.editLayout(true);
        }
        if ($location.search().refresh !== undefined) {
          if (this.refreshRate === null) {
            const refreshRate = Math.max(30, parseFloat($location.search().refresh));
            this.setRefreshRate({ name: durationHumanize(refreshRate), rate: refreshRate }, false);
          }
        }
      },
      (rejection) => {
        const statusGroup = Math.floor(rejection.status / 100);
        if (statusGroup === 5) {
          this.loadDashboard();
        } else {
          throw new PromiseRejectionError(rejection);
        }
      },
    );
  }, 1000);

  this.loadDashboard();

  this.refreshDashboard = function refreshDashboard(parameters) {
    this.refreshInProgress = true;
    collectFilters(this.dashboard, true, parameters).finally(() => {
      this.refreshInProgress = false;
    });
  }.bind(this);

  this.autoRefresh = function autoRefresh() {
    $timeout(() => {
      this.refreshDashboard();
    }, this.refreshRate.rate * 1000).then(() => {
      this.autoRefresh();
    });
  }.bind(this);

  this.archiveDashboard = function archiveDashboard() {
    const archive = function archive() {
      Events.record('archive', 'dashboard', this.dashboard.id);
      const widgets = this.dashboard.widgets;
      this.dashboard.$delete().then(() => {
        this.dashboard.widgets = widgets;
      });
    }.bind(this);
    const title = 'Archive Dashboard';
    const message = `Are you sure you want to archive the "${this.dashboard.name}" dashboard?`;
    const confirm = { class: 'btn-warning', title: 'Archive' };
    AlertDialog.open(title, message, confirm).then(archive);
  }.bind(this);

  this.showManagePermissionsModal = function showManagePermissionsModal() {
    $uibModal.open({
      component: 'permissionsEditor',
      resolve: {
        aclUrl: { url: `api/dashboards/${this.dashboard.id}/acl` },
        owner: this.dashboard.user,
      },
    });
  }.bind(this);

  this.showAddProjectDialog = function showAddProjectDialog() {
    EditProjectsDialog.showModal({
      projects: this.dashboard.project_id || [],
      getAvailableProjects: () => $http.get(`/${orgSlug}/api/available_projects`)
        .then(response => _.get(response, 'data.results', []).map(p => ({ label: p.name, value: p.id })))
        .catch(() => []),
    }).result.then((selectedProjects) => {
      this.saveDashboardProjects(selectedProjects);
    });
  }.bind(this);

  this.saveDashboardProjects = function saveDashboardProjects(selectedProjects) {
    const dashboardId = this.dashboard.id;
    $http.post(`/${orgSlug}/api/dashboards/${dashboardId}/projects`, { project_ids: selectedProjects })
      .then((response) => {
        this.dashboard.project_id = response.data.projects || [];
        notification.success('Projects updated successfully!');
      })
      .catch(() => {
        notification.error('Failed to update projects.');
      });
  }.bind(this);

  this.onLayoutChange = function onLayoutChange(positions) {
    recentPositions = positions;
    const changedPositions = getChangedPositions(this.dashboard.widgets, positions);
    if (_.isEmpty(changedPositions)) {
      this.isLayoutDirty = false;
      return;
    }
    this.isLayoutDirty = true;
    if (this.layoutEditing) {
      saveDashboardLayoutDebounced(changedPositions);
    } else {
      saveDashboardLayout(changedPositions);
    }
  }.bind(this);

  this.onBreakpointChanged = function onBreakpointChanged(isSingleCol) {
    this.isGridDisabled = isSingleCol;
    $scope.$applyAsync();
  }.bind(this);

  this.editLayout = function editLayout(isEditing) {
    this.layoutEditing = isEditing;
  }.bind(this);

  this.loadTags = function loadTags() {
    return getTags('api/dashboards/tags').then(tags => _.map(tags, t => t.name));
  };

  const updateDashboard = function updateDashboard(data) {
    _.extend(this.dashboard, data);
    const dashboardData = _.extend({}, data, {
      slug: this.dashboard.id,
      version: this.dashboard.version,
    });
    Dashboard.save(
      dashboardData,
      (dashboard) => {
        _.extend(this.dashboard, _.pick(dashboard, _.keys(data)));
      },
      (error) => {
        if (error.status === 403) {
          notification.error('Dashboard update failed', 'Permission Denied.');
        } else if (error.status === 409) {
          notification.error(
            'It seems like the dashboard has been modified by another user. Please copy/backup your changes and reload this page.',
            { duration: null },
          );
        }
      },
    );
  }.bind(this);

  this.saveName = function saveName(name) {
    updateDashboard({ name });
  };

  this.saveTags = function saveTags(tags) {
    updateDashboard({ tags });
  };

  this.updateDashboardFiltersState = function updateDashboardFiltersState() {
    collectFilters(this.dashboard, false);
    updateDashboard({
      dashboard_filters_enabled: this.dashboard.dashboard_filters_enabled,
    });
  }.bind(this);

  this.showAddTextboxDialog = function showAddTextboxDialog() {
    TextboxDialog.showModal({
      dashboard: this.dashboard,
      onConfirm: (text) => this.dashboard.addWidget(text).then(this.onWidgetAdded),
    });
  }.bind(this);

  this.showAddWidgetDialog = function showAddWidgetDialog() {
    AddWidgetDialog.showModal({
      dashboard: this.dashboard,
      onConfirm: (visualization, parameterMappings) => this.dashboard.addWidget(visualization, {
        parameterMappings: editableMappingsToParameterMappings(parameterMappings),
      }).then((widget) => {
        const widgetsToSave = [
          widget,
          ...synchronizeWidgetTitles(widget.options.parameterMappings, this.dashboard.widgets),
        ];
        return $q.all(widgetsToSave.map(w => w.save())).then(this.onWidgetAdded);
      }),
    });
  }.bind(this);

  this.onWidgetAdded = function onWidgetAdded() {
    this.extractGlobalParameters();
    collectFilters(this.dashboard, false);
    $scope.$applyAsync();
  }.bind(this);

  this.removeWidget = function removeWidget(widgetId) {
    this.dashboard.widgets = this.dashboard.widgets.filter(w => w.id !== undefined && w.id !== widgetId);
    this.extractGlobalParameters();
    collectFilters(this.dashboard, false);
    $scope.$applyAsync();
  }.bind(this);

  this.toggleFullscreen = function toggleFullscreen() {
    this.isFullscreen = !this.isFullscreen;
    document.querySelector('body').classList.toggle('headless');
    if (this.isFullscreen) {
      $location.search('fullscreen', true);
    } else {
      $location.search('fullscreen', null);
    }
  }.bind(this);

  this.togglePublished = function togglePublished() {
    Events.record('toggle_published', 'dashboard', this.dashboard.id);
    this.dashboard.is_draft = !this.dashboard.is_draft;
    this.saveInProgress = true;
    Dashboard.save(
      {
        slug: this.dashboard.id,
        name: this.dashboard.name,
        is_draft: this.dashboard.is_draft,
      },
      (dashboard) => {
        this.saveInProgress = false;
        this.dashboard.version = dashboard.version;
      },
    );
  }.bind(this);

  if (_.has($location.search(), 'fullscreen')) {
    this.toggleFullscreen();
  }

  this.openShareForm = function openShareForm() {
    const hasOnlySafeQueries = _.every(
      this.dashboard.widgets,
      w => (w.getQuery() ? w.getQuery().is_safe : true),
    );
    ShareDashboardDialog.showModal({
      dashboard: this.dashboard,
      hasOnlySafeQueries,
    });
  }.bind(this);
}

export default function init(ngModule) {
  // Register controller by name
  ngModule.controller('DashboardCtrl', DashboardCtrl);

  ngModule.component('dashboardPage', {
    template,
    // Reference controller by its registered name
    controller: 'DashboardCtrl',
  });

  return {
    '/dashboard/:dashboardSlug': {
      template: '<dashboard-page></dashboard-page>',
      reloadOnSearch: false,
    },
  };
}

init.init = true;