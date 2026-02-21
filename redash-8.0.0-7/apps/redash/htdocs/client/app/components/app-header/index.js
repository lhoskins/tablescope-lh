import debug from 'debug';
import CreateDashboardDialog from '@/components/dashboards/CreateDashboardDialog';
import logoUrl from '@/assets/images/TableScope_logo.png';
import toggleNavIcon from '@/assets/images/toggle-nav.png';
import frontendVersion from '@/version.json';
import template from './app-header.html';
import './app-header.css';

const logger = debug('redash:appHeader');

function controller($rootScope, $location, $route, $uibModal, Auth, currentUser, clientConfig, Dashboard, Query) {
  this.logoUrl = logoUrl;
  this.toggleNavIcon = toggleNavIcon;
  this.basePath = clientConfig.basePath;
  this.currentUser = currentUser;
  this.showQueriesMenu = currentUser.hasPermission('view_query');
  this.showAlertsLink = currentUser.hasPermission('list_alerts');
  this.showNewQueryMenu = currentUser.hasPermission('create_query');
  this.showSettingsMenu = currentUser.hasPermission('list_users');
  this.showDashboardsMenu = currentUser.hasPermission('list_dashboards');

  this.frontendVersion = frontendVersion;
  this.backendVersion = clientConfig.version;
  this.newVersionAvailable = clientConfig.newVersionAvailable && currentUser.isAdmin;

  this.reload = () => {
    logger('Reloading dashboards and queries.');
    Dashboard.favorites().$promise.then((data) => {
      this.dashboards = data.results;
    });
    Query.favorites().$promise.then((data) => {
      this.queries = data.results;
    });
  };

  this.reload();

  $rootScope.$on('reloadFavorites', this.reload);

  this.newDashboard = () => CreateDashboardDialog.showModal();

  this.searchQueries = () => {
    $location.path('/queries').search({ q: this.searchTerm });
    $route.reload();
  };

  this.logout = () => {
    Auth.logout();
  };

  this.getRoleDisplayName = (roleType) => {
    const roleNames = {
      default: 'Default',
      designer: 'Designer',
      project_owner: 'Project Owner',
      project_admin: 'Project Admin',
      organization_admin: 'Organization Admin',
      super_admin: 'Super Admin',
    };
    return roleNames[roleType] || roleType;
  };

  this.showUsersView = () => {
    // Navigate to home page first
    if ($location.path() !== '/') {
      $location.path('/');
      // Wait for navigation to complete before triggering event
      setTimeout(() => {
        document.dispatchEvent(new CustomEvent('showUsersView'));
      }, 100);
    } else {
      // Already on home page, trigger event immediately
      document.dispatchEvent(new CustomEvent('showUsersView'));
    }
  };

  this.toggleNavigation = () => {
    // Dispatch event to toggle the navigation pane
    document.dispatchEvent(new CustomEvent('toggleNavigationPane'));
  };
}

export default function init(ngModule) {
  ngModule.component('appHeader', {
    template,
    controller,
  });
}

init.init = true;
