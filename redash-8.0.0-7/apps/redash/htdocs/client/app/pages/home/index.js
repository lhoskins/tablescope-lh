/* ------------------------------------------------------------------
   TableScopeHome.jsx – central container for the TS workspace
------------------------------------------------------------------ */
/* eslint-disable react/prop-types, react/no-danger */

import React, { useState, useEffect, useRef } from 'react';
import { react2angular } from 'react2angular';
import { routesToAngularRoutes } from '@/lib/utils';

import NavigationPane from '@/pages/NavigationPane/NavigationPane';
import DropzonePage from '@/pages/dropzone/DropzonePage';
import ProjectDetailPage from '@/pages/NavigationPane/ProjectDetailPage';
import DataSourceViewer from '@/pages/NavigationPane/DataSourceViewer';
import UsersListPage from '@/pages/NavigationPane/UsersListPage';
import NewUserPage from '@/pages/NavigationPane/NewUserPage';
import UserEditPage from '@/pages/NavigationPane/UserEditPage';

import toggleIcon from '@/assets/images/toggle-nav.png';
import tableScopeLogo from '@/assets/images/TableScope_logo.png';
import { TSQueryEditorReact as TSQueryEditor } from '@/components/TSQueryEditor';

/* plus-button helpers */
import CreateProjectDialog from '@/components/projects/CreateProjectDialog';
import { currentUser } from '@/services/auth';

/* ─────────────────────────  Shared look-and-feel  ───────────────────────── */
const WINDOW_BORDER = '0.5px solid #e0e0e0';

export const WINDOW_STYLE = {
  backgroundColor: '#ffffff',
  border: WINDOW_BORDER,
  borderRadius: 4,
  width: '100%',
  height: '100%', // Ensure the window fills the container
  boxSizing: 'border-box',
  display: 'flex',
  flexDirection: 'column',
  flex: '1 1 auto',
  minWidth: 0,
};

export const WINDOW_BODY_STYLE = {
  padding: '0.75rem',
  width: '100%',
  flex: '1 1 auto',
  minWidth: 0,
  overflow: 'hidden', // The body itself should not scroll, it should contain the child
  display: 'flex',
  flexDirection: 'column',
};

// The HTML content from `dashboard.html` is now stored in a constant.
const dashboardTemplate = `
<div class="container" style="height: 100%; display: flex; flex-direction: column;">
  <div class="row p-l-15 p-r-15 m-b-10 m-l-0 m-r-0 dashboard-header page-header--new">
    <div class="page-title col-xs-8 col-sm-7 col-lg-7 p-l-0">
      <favorites-control item="$ctrl.dashboard"></favorites-control>
      <h3>
        <edit-in-place class="edit-in-place" is-editable="$ctrl.layoutEditing" on-done="$ctrl.saveName" ignore-blanks="true" value="$ctrl.dashboard.name" editor="'input'"></edit-in-place>
      </h3>
      <img ng-src="{{$ctrl.dashboard.user.profile_image_url}}" class="profile__image_thumb--dashboard" alt="{{$ctrl.dashboard.user.name}}" />
      <dashboard-tags-control class="hidden-xs"
        tags="$ctrl.dashboard.tags" is-draft="$ctrl.dashboard.is_draft" is-archived="$ctrl.dashboard.is_archived"
        can-edit="$ctrl.isDashboardOwner" get-available-tags="$ctrl.loadTags" on-edit="$ctrl.saveTags"></dashboard-tags-control>
    </div>
    <div class="col-xs-4 col-sm-5 col-lg-5 text-right dashboard__control p-r-0">
      <span ng-if="!$ctrl.dashboard.is_archived && !public" class="hidden-print">
          <div ng-if="$ctrl.layoutEditing" ng-switch="$ctrl.isLayoutDirty">
            <span ng-switch-when="true" ng-switch="$ctrl.saveInProgress || $ctrl.saveDelay">
                <span ng-switch-when="true">
                  <span class="save-status" data-saving>Saving</span>
                  <button class="btn btn-primary btn-sm" ng-disabled="$ctrl.editBtnClickedWhileSaving" ng-click="$ctrl.editBtnClickedWhileSaving = true">
                    <i class="fa fa-check" ng-class="{'fa-spinner fa-pulse': $ctrl.editBtnClickedWhileSaving}"></i> Done Editing
                  </button>
                </span>
                <span ng-switch-default>
                  <span class="save-status" data-error>Saving Failed</span>
                  <button class="btn btn-primary btn-sm" ng-click="$ctrl.retrySaveDashboardLayout()">
                    Retry
                  </button>
                </span>
            </span>
            <span ng-switch-default>
              <span class="save-status">Saved</span>
              <button class="btn btn-primary btn-sm"
                ng-disabled="$ctrl.isGridDisabled"
                ng-click="$ctrl.editLayout(false)">
                <i class="fa fa-check"></i> Done Editing
              </button>
            </span>
          </div>
          <button type="button" class="btn btn-default btn-sm" ng-click="$ctrl.togglePublished()" tooltip="Publish Dashboard" ng-if="$ctrl.dashboard.is_draft && !$ctrl.layoutEditing">
            <span class="fa fa-paper-plane"></span> Publish
          </button>
          <div class="btn-group" uib-dropdown ng-if="!$ctrl.layoutEditing">
            <button id="split-button" type="button"
                    ng-class="{'btn-default btn-sm': $ctrl.refreshRate === null, 'btn-primary btn-sm': $ctrl.refreshRate !== null}"
                    class="btn btn-sm" ng-click="$ctrl.refreshDashboard()">
              <i class="zmdi zmdi-refresh" ng-class="{'zmdi-hc-spin': $ctrl.refreshInProgress}"></i> {{$ctrl.refreshRate === null ? 'Refresh' : $ctrl.refreshRate.name}}
            </button>
            <button type="button" class="btn hidden-xs" uib-dropdown-toggle
                    ng-class="{'btn-default btn-sm': $ctrl.refreshRate === null, 'btn-primary btn-sm': $ctrl.refreshRate !== null}">
              <span class="caret"></span>
              <span class="sr-only">Split button!</span>
            </button>
            <ul class="dropdown-menu pull-right" ng-model="$ctrl.refreshRate" uib-dropdown-menu role="menu" aria-labelledby="split-button">
              <li role="menuitem" ng-repeat="refreshRate in $ctrl.refreshRates" ng-class="{disabled: !refreshRate.enabled}">
                <a ng-click="$ctrl.setRefreshRate(refreshRate)">{{refreshRate.name}}</a>
              </li>
              <li role="menuitem" ng-if="$ctrl.refreshRate !== null">
                <a href="#" ng-click="$ctrl.setRefreshRate(null)">Stop auto refresh</a>
              </li>
            </ul>
          </div>
          <button type="button" class="btn btn-sm hidden-xs" ng-class="{'btn-default': !$ctrl.isFullscreen, 'btn-primary': $ctrl.isFullscreen}" tooltip="Enable/Disable Fullscreen display" ng-click="$ctrl.toggleFullscreen()" ng-if="!$ctrl.dashboard.is_draft && !$ctrl.layoutEditing">
            <span class="zmdi zmdi-fullscreen"></span>
          </button>
          <button type="button" class="btn btn-sm hidden-xs" ng-class="{'btn-default': !$ctrl.dashboard.publicAccessEnabled, 'btn-primary': $ctrl.dashboard.publicAccessEnabled}" tooltip="Enable/Disable Share URL" ng-click="$ctrl.openShareForm()" ng-if="($ctrl.dashboard.canEdit() || $ctrl.dashboard.publicAccessEnabled) && !$ctrl.dashboard.is_draft && !$ctrl.layoutEditing" data-test="OpenShareForm">
            <span class="zmdi zmdi-share"></span>
          </button>
      </span>
      <div class="btn-group hidden-print hidden-xs" role="group" ng-show="$ctrl.dashboard.canEdit()" uib-dropdown ng-if="!$ctrl.dashboard.is_archived && !$ctrl.layoutEditing" data-test="DashboardMoreMenu">
        <button class="btn btn-default btn-sm dropdown-toggle" uib-dropdown-toggle>
          <span class="zmdi zmdi-more"></span>
        </button>
        <ul class="dropdown-menu pull-right" uib-dropdown-menu>
          <li ng-if="!$ctrl.dashboard.is_archived" ng-class="{hidden: $ctrl.isGridDisabled}"><a ng-click="$ctrl.editLayout(true)">Edit</a></li>
          <li ng-if="$ctrl.showPermissionsControl"><a ng-click="$ctrl.showManagePermissionsModal()">Manage Permissions</a></li>
          <li ng-if="!$ctrl.dashboard.is_draft"><a ng-click="$ctrl.togglePublished()">Unpublish</a></li>
          <li ng-if="!$ctrl.dashboard.is_archived"><a ng-click="$ctrl.archiveDashboard()">Archive</a></li>
        </ul>
      </div>
    </div>
  </div>

  <div class="m-b-10 p-15 bg-white tiled" ng-if="$ctrl.layoutEditing">
    <label>
      <input name="input" type="checkbox" ng-model="$ctrl.dashboard.dashboard_filters_enabled" ng-change="$ctrl.updateDashboardFiltersState()">
      Use Dashboard Level Filters
    </label>
  </div>

  <div class="m-b-10 p-15 bg-white tiled" ng-if="$ctrl.globalParameters.length > 0">
    <parameters parameters="$ctrl.globalParameters" on-values-change="$ctrl.refreshDashboard"></parameters>
  </div>

  <div class="m-b-10 p-15 bg-white tiled" ng-if="$ctrl.filters | notEmpty">
    <filters filters="$ctrl.filters" on-change="$ctrl.filtersOnChange"></filters>
  </div>

  <div id="dashboard-container" style="flex: 1 1 auto; overflow-y: auto;">
    <dashboard-grid
      ng-if="$ctrl.dashboard"
      dashboard="$ctrl.dashboard"
      widgets="$ctrl.dashboard.widgets"
      filters="$ctrl.filters"
      is-editing="$ctrl.layoutEditing && !$ctrl.isGridDisabled"
      on-layout-change="$ctrl.onLayoutChange"
      on-breakpoint-change="$ctrl.onBreakpointChanged"
      on-remove-widget="$ctrl.removeWidget"
    />
  </div>

  <div class="add-widget-container" ng-if="$ctrl.layoutEditing">
    <h2>
      <i class="zmdi zmdi-widgets"></i>
      <span class="hidden-xs hidden-sm">
        Widgets are individual query visualizations or text boxes you can place on your dashboard in various arrangements.
      </span>
    </h2>
    <div>
      <a class="btn btn-default m-r-10" ng-click="$ctrl.showAddProjectDialog()">Add Project</a>
      <a class="btn btn-default" ng-click="$ctrl.showAddTextboxDialog()">Add Textbox</a>
      <a class="btn btn-primary m-l-10" ng-click="$ctrl.showAddWidgetDialog()">Add Widget</a>
    </div>
  </div>
</div>
`;

/* ========================================================================
   Helper – embeds the legacy Angular TSQuery page inline
   ====================================================================== */
function AngularTSQuery({ queryId, workspace = 'ts' }) {
  const container = useRef(null);

  useEffect(() => {
    const ng = window.angular;
    if (!ng || !container.current) return undefined;

    const rootEl = document.body;
    const injector = ng.element(rootEl).injector();
    if (!injector) return undefined;

    const $q = injector.get('$q');
    const $compile = injector.get('$compile');
    const $controller = injector.get('$controller');
    const $rootScope = injector.get('$rootScope');
    const $http = injector.get('$http');
    const Query = injector.get('Query');
    const DataSource = injector.get('DataSource');

    const templatePath =
      workspace === 'tc' ? '/static/js/TSqueryCode.html' : '/static/js/TSquery.html';

    const tplPr = $http.get(templatePath).then(r => r.data);
    const qryPr = Query.get({ id: queryId }).$promise;
    const dssPr = DataSource.query().$promise;

    let scoped;
    let el;

    $q
      .all([tplPr, qryPr, dssPr])
      .then(([html, queryObj, dataSources]) => {
        const fakeRoute = {
          current: { params: { queryId }, locals: { query: queryObj, dataSources } },
        };

        scoped = $rootScope.$new(true);
        scoped.$routeParams = { queryId };
        scoped.sourceMode = workspace === 'tc';

        let ctrlName = 'QueryViewCtrl';
        if (workspace === 'tc' && injector.has('QuerySourceCtrl')) ctrlName = 'QuerySourceCtrl';
        else if (injector.has('TSQueryViewCtrl')) ctrlName = 'TSQueryViewCtrl';

        $controller(ctrlName, { $scope: scoped, $route: fakeRoute });

        scoped.$watch(
          () => scoped.queryResult && scoped.queryResult.getStatus(),
          (status) => {
            if (status === 'done') scoped.showDataset = true;
          },
        );

        el = $compile(html)(scoped);
        el.css({ width: '100%', height: '100%', minWidth: 0, flex: '1 1 auto' });

        container.current.innerHTML = '';
        container.current.appendChild(el[0]);
        scoped.$applyAsync();
      })
      .catch(err => console.error('[AngularTSQuery] bootstrap failed:', err));

    return () => {
      if (scoped) scoped.$destroy();
      if (el && el[0] && el[0].parentNode) el[0].parentNode.removeChild(el[0]);
    };
  }, [queryId, workspace]);

  // This container is now a scrolling flex child.
  return (
    <div
      ref={container}
      style={{
        flex: '1 1 auto',
        minHeight: 0,
        overflow: 'auto',
      }}
    />
  );
}

/* ========================================================================
   Helper – embeds the legacy Angular Dashboard page inline
   ====================================================================== */
function AngularDashboard({ slug }) {
  const container = useRef(null);

  useEffect(() => {
    const ng = window.angular;
    if (!ng || !container.current) return;

    const injector = ng.element(document.body).injector();
    if (!injector) return;

    const $compile = injector.get('$compile');
    const $controller = injector.get('$controller');
    const $rootScope = injector.get('$rootScope');

    const scoped = $rootScope.$new(true);
    const locals = {
      $scope: scoped,
      $routeParams: { dashboardSlug: slug },
    };

    // Instantiate the controller and attach it to the scope.
    scoped.$ctrl = $controller('DashboardCtrl', locals);

    // Compile the dashboard template with the new scope.
    const el = $compile(dashboardTemplate)(scoped);
    el.css({
      width: '100%',
      height: '100%',
      minWidth: 0,
      flex: '1 1 auto',
      display: 'flex',
      flexDirection: 'column',
    });

    container.current.innerHTML = '';
    container.current.appendChild(el[0]);
    scoped.$applyAsync();

    // Cleanup when the component unmounts.
    // eslint-disable-next-line consistent-return
    return () => {
      scoped.$destroy();
      if (el && el[0] && el[0].parentNode) {
        el[0].parentNode.removeChild(el[0]);
      }
    };
  }, [slug]);

  return (
    <div
      ref={container}
      style={{
        flex: '1 1 auto',
        minHeight: 0,
        overflow: 'auto',
      }}
    />
  );
}


/* ========================================================================
   Main React component
   ====================================================================== */
function TableScopeHome() {
  const MIN_NAV_W = 32;
  const [navWidth, setNavWidth] = useState(250);
  const prevWidth = useRef(navWidth);
  const isDragging = useRef(false);

  const [selectedProjectId, setSelectedProjectId] = useState(null);
  const [selectedQueryId, setSelectedQueryId] = useState(null);
  const [codeMode, setCodeMode] = useState(false);
  const [selectedDashboardSlug, setSelectedDashboardSlug] = useState(null);
  const [selectedDataSource, setSelectedDataSource] = useState(null);
  const [showUsersView, setShowUsersView] = useState(false);
  const [showNewUserView, setShowNewUserView] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState(null);
  const [showGroupsView, setShowGroupsView] = useState(false);
  const [showNewGroupView, setShowNewGroupView] = useState(false);
  const [selectedGroupId, setSelectedGroupId] = useState(null);

  const mainRef = useRef(null);

  /* broadcast the active project for other widgets */
  useEffect(() => {
    if (selectedProjectId !== null) {
      window.__currentProjectId = selectedProjectId;
      document.dispatchEvent(
        new CustomEvent('project-selected', { detail: { projectId: selectedProjectId } }),
      );
    }
  }, [selectedProjectId]);

  /* ─── Project creation dialog ───────────────────────────── */
  const createProject = () => {
    CreateProjectDialog.showModal().result
      .then(project => project.$save().then((newProject) => {
        setSelectedProjectId(newProject.id);
        setSelectedQueryId(null);
        setCodeMode(false);
        // Trigger refresh of navigation pane to show new project
        document.dispatchEvent(new CustomEvent('refresh-navigation'));
      }))
      .catch(() => {});
  };

  /* ─── resizable navigation pane ─────────────────────────── */
  const startDragging = (e) => {
    e.preventDefault();
    isDragging.current = true;
  };
  useEffect(() => {
    const handleMouseMove = (e) => {
      if (!isDragging.current) return;
      const newW = Math.min(Math.max(e.clientX, MIN_NAV_W), 600);
      setNavWidth(newW);
    };
    const stopDragging = () => (isDragging.current = false);
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', stopDragging);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', stopDragging);
    };
  }, []);

  /* auto-open code viewer if URL already /source */
  useEffect(() => {
    const m = window.location.pathname.match(/\/(?:tc|ts)queries\/(\d+)\/source/);
    if (m) {
      const id = Number(m[1]);
      if (!Number.isNaN(id)) {
        setSelectedQueryId(id);
        setCodeMode(true);
      }
    }
  }, []);

  /* Check for pending project selection from localStorage */
  useEffect(() => {
    console.log('[TableScopeHome] Component mounted, checking for pending project selection');
    
    // Check localStorage first
    try {
      const pendingProjectId = localStorage.getItem('__pendingProjectSelection');
      if (pendingProjectId) {
        const projectId = parseInt(pendingProjectId, 10);
        console.log('[TableScopeHome] Found pending project selection in localStorage:', projectId);
        
        if (!isNaN(projectId)) {
          // Clear the localStorage item
          localStorage.removeItem('__pendingProjectSelection');
          
          // Set the selected project
          setSelectedProjectId(projectId);
          setSelectedQueryId(null);
          setCodeMode(false);
          setSelectedDashboardSlug(null);
          setSelectedDataSource(null);
          setShowUsersView(false);
          
          console.log('[TableScopeHome] Set selectedProjectId to:', projectId);
          return;
        }
      }
    } catch (e) {
      console.error('[TableScopeHome] Error reading localStorage:', e);
    }
    
    // Check global variables as fallback
    if (window.__pendingProjectSelection) {
      const projectId = parseInt(window.__pendingProjectSelection, 10);
      console.log('[TableScopeHome] Found pending project selection in window:', projectId);
      
      if (!isNaN(projectId)) {
        setSelectedProjectId(projectId);
        setSelectedQueryId(null);
        setCodeMode(false);
        setSelectedDashboardSlug(null);
        setSelectedDataSource(null);
        setShowUsersView(false);
        
        // Clear the global variable
        delete window.__pendingProjectSelection;
        
        console.log('[TableScopeHome] Set selectedProjectId to:', projectId);
      }
    }
  }, []);

  /* callbacks from NavigationPane */
  const handleProjectSelected = (pid) => {
    setSelectedProjectId(pid);
    setSelectedQueryId(null);
    setCodeMode(false);
    setSelectedDashboardSlug(null);
    setSelectedDataSource(null);
    setShowUsersView(false);
  };

  const handleQuerySelected = (qid) => {
    setSelectedQueryId(qid);
    setCodeMode(false);
    setSelectedDashboardSlug(null);
    setSelectedDataSource(null);
    setShowUsersView(false);
    document.dispatchEvent(new CustomEvent('query-selected', { detail: { queryId: qid } }));
  };

  const handleDashboardSelected = (slug) => {
    setSelectedDashboardSlug(slug);
    setSelectedQueryId(null);
    setSelectedDataSource(null);
    setShowUsersView(false);
    // broadcast if anything listening
    document.dispatchEvent(new CustomEvent('dashboard-selected', { detail: { slug } }));
  };

  const handleDataSourceSelected = (dataSource) => {
    setSelectedDataSource(dataSource);
    setSelectedQueryId(null);
    setSelectedDashboardSlug(null);
    setShowUsersView(false);
    // broadcast if anything listening
    document.dispatchEvent(new CustomEvent('datasource-selected', { detail: { dataSource } }));
  };

  const handleUsersViewSelected = () => {
    setShowUsersView(true);
    setShowNewUserView(false);
    setSelectedQueryId(null);
    setSelectedDashboardSlug(null);
    setSelectedDataSource(null);
    setSelectedProjectId(null);
    setShowGroupsView(false);
    setShowNewGroupView(false);
    setSelectedGroupId(null);
  };

  const handleGroupsViewSelected = () => {
    setShowGroupsView(true);
    setShowNewGroupView(false);
    setSelectedQueryId(null);
    setSelectedDashboardSlug(null);
    setSelectedDataSource(null);
    setSelectedProjectId(null);
    setShowUsersView(false);
    setShowNewUserView(false);
    setSelectedUserId(null);
  };

  /* external event for "showUsersView" from dropdown menu */
  useEffect(() => {
    const handler = () => {
      handleUsersViewSelected();
    };
    document.addEventListener('showUsersView', handler);
    return () => {
      document.removeEventListener('showUsersView', handler);
    };
  }, []);

  /* external event for "showGroupsView" from dropdown menu */
  useEffect(() => {
    const handler = () => {
      handleGroupsViewSelected();
    };
    document.addEventListener('showGroupsView', handler);
    return () => {
      document.removeEventListener('showGroupsView', handler);
    };
  }, []);

  /* Listen for navigation pane toggle */
  useEffect(() => {
    const handler = () => {
      setNavWidth((currentWidth) => {
        if (currentWidth > MIN_NAV_W) {
          // Collapse: save current width and set to minimum
          prevWidth.current = currentWidth;
          return MIN_NAV_W;
        }
        // Expand: restore previous width or default to 250
        return prevWidth.current > MIN_NAV_W ? prevWidth.current : 250;
      });
    };
    document.addEventListener('toggleNavigationPane', handler);
    return () => {
      document.removeEventListener('toggleNavigationPane', handler);
    };
  }, [MIN_NAV_W]);

  /* Listen for project deletion to clear selected project */
  useEffect(() => {
    const handler = (e) => {
      const deletedProjectId = e.detail?.projectId;
      if (deletedProjectId && selectedProjectId === deletedProjectId) {
        setSelectedProjectId(null);
        setSelectedQueryId(null);
        setCodeMode(false);
      }
    };
    document.addEventListener('project-deleted', handler);
    return () => {
      document.removeEventListener('project-deleted', handler);
    };
  }, [selectedProjectId]);

  /* Intercept Angular navigation to /users when in new user or users view */
  useEffect(() => {
    const ng = window.angular;
    if (!ng) return undefined;

    const injector = ng.element(document.body).injector();
    if (!injector) return undefined;

    const $rootScope = injector.get('$rootScope');
    
    const locationChangeListener = $rootScope.$on('$locationChangeStart', (event, newUrl, oldUrl) => {
      // If we're showing users-related views, intercept navigation
      if ((showUsersView || showNewUserView || selectedUserId)) {
        // Check if navigating to /users (list page)
        const listMatch = newUrl.match(/\/users(?:\?|$|#)/);
        if (listMatch) {
          event.preventDefault();
          setShowUsersView(true);
          setShowNewUserView(false);
          setSelectedUserId(null);
          return;
        }
        
        // Check if navigating to /users/:id (edit page)
        const editMatch = newUrl.match(/\/users\/(\d+)/);
        if (editMatch) {
          event.preventDefault();
          const userId = editMatch[1];
          setSelectedUserId(userId);
          setShowUsersView(false);
          setShowNewUserView(false);
        }
      }
      
      // If we're showing groups-related views, intercept navigation
      if ((showGroupsView || showNewGroupView || selectedGroupId)) {
        // Check if navigating to /groups (list page)
        const listMatch = newUrl.match(/\/groups(?:\?|$|#)/);
        if (listMatch) {
          event.preventDefault();
          setShowGroupsView(true);
          setShowNewGroupView(false);
          setSelectedGroupId(null);
          return;
        }
        
        // Check if navigating to /groups/:id (edit page)
        const editMatch = newUrl.match(/\/groups\/(\d+)/);
        if (editMatch) {
          event.preventDefault();
          const groupId = editMatch[1];
          setSelectedGroupId(groupId);
          setShowGroupsView(false);
          setShowNewGroupView(false);
        }
      }
    });

    return () => {
      locationChangeListener();
    };
  }, [showUsersView, showNewUserView, selectedUserId, showGroupsView, showNewGroupView, selectedGroupId]);


  /* external event for “openCodeEditor” */
  useEffect(() => {
    const handler = (e) => {
      const { queryId } = e.detail;
      setSelectedQueryId(queryId);
      setCodeMode(true);
      setSelectedDashboardSlug(null);
    };
    document.addEventListener('openCodeEditor', handler);
    return () => document.removeEventListener('openCodeEditor', handler);
  }, []);

  /* ─────────────────────────  right-pane selector  ───────────────────────── */
  let content;

  if (selectedUserId) {
    /* User edit view */
    content = (
      <div style={WINDOW_STYLE}>
        <div style={{ 
          padding: '0.5rem 0.75rem', 
          borderBottom: WINDOW_BORDER, 
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <button
              type="button"
              className="btn btn-sm btn-default"
              onClick={() => {
                setSelectedUserId(null);
                setShowUsersView(true);
              }}
            >
              ← Back to Users
            </button>
            <h3 style={{ margin: 0 }}>Edit User</h3>
          </div>
        </div>
        <div style={{ ...WINDOW_BODY_STYLE, padding: 0, overflow: 'hidden' }}>
          <UserEditPage userId={selectedUserId} onBack={() => {
            setSelectedUserId(null);
            setShowUsersView(true);
          }} />
        </div>
      </div>
    );
  } else if (showNewUserView) {
    /* New user form view */
    content = (
      <div style={WINDOW_STYLE}>
        <div style={{ 
          padding: '0.5rem 0.75rem', 
          borderBottom: WINDOW_BORDER, 
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <button
              type="button"
              className="btn btn-sm btn-default"
              onClick={() => {
                setShowNewUserView(false);
                setShowUsersView(true);
              }}
            >
              ← Back to Users
            </button>
            <h3 style={{ margin: 0 }}>Create New User</h3>
          </div>
        </div>
        <div style={{ ...WINDOW_BODY_STYLE, padding: 0, overflow: 'hidden' }}>
          <NewUserPage onBack={() => {
            setShowNewUserView(false);
            setShowUsersView(true);
          }} />
        </div>
      </div>
    );
  } else if (showUsersView) {
    /* Users list view */
    content = (
      <div style={WINDOW_STYLE}>
        <div style={{ 
          padding: '0.5rem 0.75rem', 
          borderBottom: WINDOW_BORDER, 
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginTop: '20px'
        }}>
          <h3 style={{ margin: 0 }}>Users Management</h3>
          {currentUser.isAdmin && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => {
                setShowNewUserView(true);
                setShowUsersView(false);
              }}
            >
              <i className="fa fa-plus" style={{ marginRight: '5px' }} />
              New User
            </button>
          )}
        </div>
        <div style={{ ...WINDOW_BODY_STYLE, padding: 0, overflow: 'hidden' }}>
          <UsersListPage />
        </div>
      </div>
    );
  } else if (selectedDataSource) {
    /* DataSource viewer */
    content = (
      <div style={WINDOW_STYLE}>
        <div style={{ padding: '0.5rem 0.75rem', borderBottom: WINDOW_BORDER, flexShrink: 0 }}>
          <button
            type="button"
            className="btn btn-sm btn-default"
            onClick={() => {
              setSelectedDataSource(null);
            }}
          >
            ← Back
          </button>
        </div>
        <div style={{ ...WINDOW_BODY_STYLE, padding: 0, overflow: 'hidden' }}>
          <DataSourceViewer 
            dataSource={selectedDataSource}
            onBack={() => setSelectedDataSource(null)}
          />
        </div>
      </div>
    );
  } else if (selectedDashboardSlug) {
    content = (
      <div style={WINDOW_STYLE}>
        <div style={{ padding: '0.5rem 0.75rem', borderBottom: WINDOW_BORDER, flexShrink: 0 }}>
          <button
            type="button"
            className="btn btn-sm btn-default"
            onClick={() => {
              setSelectedDashboardSlug(null);
            }}
          >
            ← Back to Project
          </button>
        </div>
        <div style={{ ...WINDOW_BODY_STYLE, padding: 0, overflow: 'hidden' }}>
          <AngularDashboard slug={selectedDashboardSlug} />
        </div>
      </div>
    );
  } else
  if (selectedQueryId === 'new') {
    /* New query → render visual editor directly */
    content = (
      <div style={WINDOW_STYLE}>
        <div style={{ padding: '0.5rem 0.75rem', borderBottom: WINDOW_BORDER, flexShrink: 0 }}>
          <button
            type="button"
            className="btn btn-sm btn-default"
            onClick={() => {
              setSelectedQueryId(null);
              setCodeMode(false);
            }}
          >
            ← Back to Project
          </button>
        </div>
        <div style={WINDOW_BODY_STYLE}>
          <TSQueryEditor isNew projectId={selectedProjectId} />
        </div>
      </div>
    );
  } else if (selectedQueryId !== null) {
    /* Existing query – Angular viewer (tc or ts) */
    content = (
      <div style={WINDOW_STYLE}>
        <div style={{ padding: '0.5rem 0.75rem', borderBottom: WINDOW_BORDER, flexShrink: 0 }}>
          <button
            type="button"
            className="btn btn-sm btn-default"
            onClick={() => {
              setSelectedQueryId(null);
              setCodeMode(false);
            }}
          >
            ← Back to Project
          </button>
        </div>
        <div style={WINDOW_BODY_STYLE}>
          <AngularTSQuery queryId={selectedQueryId} workspace={codeMode ? 'tc' : 'ts'} />
        </div>
      </div>
    );
  } else if (selectedProjectId !== null) {
    /* Project-level view */
    content = (
      <div style={WINDOW_STYLE}>
        <div style={WINDOW_BODY_STYLE}>
          <ProjectDetailPage projectId={selectedProjectId} onQuerySelected={handleQuerySelected} onDashboardSelected={handleDashboardSelected} />
        </div>
      </div>
    );
  } else {
    /* First-time landing page */
    content = (
      <div style={WINDOW_STYLE}>
        <div style={WINDOW_BODY_STYLE}>
          <DropzonePage />
        </div>
      </div>
    );
  }

  /* ───────────────────── layout ───────────────────── */
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Main Content Area */}
      <div style={{ display: 'flex', flex: '1 1 auto', overflow: 'hidden' }}>
        {/* NAV */}
        <div
          style={{
            width: navWidth,
            background: '#ffffff',
            position: 'relative',
            overflow: 'hidden',
            transition: 'width 0.15s ease',
            minWidth: MIN_NAV_W,
            flexShrink: 0,
            borderRight: '0.5px solid #e0e0e0',
            borderTop: '0.5px solid #e0e0e0',
          }}
        >
          {navWidth > MIN_NAV_W && (
            <div style={{ height: '100%', overflow: 'hidden' }}>
              <NavigationPane
                onProjectSelected={handleProjectSelected}
                onQuerySelected={handleQuerySelected}
                onDashboardSelected={handleDashboardSelected}
                onDataSourceSelected={handleDataSourceSelected}
                createProject={createProject}
              />
            </div>
          )}
        </div>

        {/* drag handle */}
        <div
          role="presentation"
          onMouseDown={startDragging}
          style={{ width: 0.5, cursor: 'col-resize', background: 'transparent', flexShrink: 0, marginLeft: -2, marginRight: -2 }}
        />

        {/* MAIN WORKSPACE */}
        <div
          ref={mainRef}
          style={{
            flex: '1 1 auto',
            display: 'flex',
            flexDirection: 'column',
            padding: '0.5rem',
            paddingTop: 0,
            background: '#f0f0f0',
            minWidth: 0,
            minHeight: 0,
            overflow: 'hidden',
          }}
        >
          {content}
        </div>
      </div>
    </div>
  );
}

/* ========================================================================
   Angular registration
   ====================================================================== */
export default function init(ngModule) {
  ngModule.component('tableScopeHome', react2angular(TableScopeHome));

  return routesToAngularRoutes(
    [
      { path: '/', title: 'TS Home', key: 'tshome' },
      { path: '/tcqueries/:queryId', title: 'TS Query', key: 'tcquery' },
      { path: '/tcqueries/:queryId/source', title: 'TS Query Source', key: 'tcquerysource' },
      { path: '/tsqueries/:queryId', title: 'TS Query', key: 'tsquery' },
      { path: '/tsqueries/:queryId/source', title: 'TS Query Source', key: 'tsquerysource' },
    ],
    {
      reloadOnSearch: false,
      template: '<table-scope-home></table-scope-home>',
      controller($scope, $exceptionHandler) {
        'ngInject';

        $scope.handleError = $exceptionHandler;
      },
    },
  );
}
init.init = true;
