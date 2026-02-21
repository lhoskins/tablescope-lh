import { extend } from 'lodash';
import { routesToAngularRoutes } from '@/lib/utils';

export default function init() {
  const listRoutes = routesToAngularRoutes([
    {
      path: '/users',
      title: 'Users',
      key: 'active',
    },
    {
      path: '/users/new',
      title: 'Users',
      key: 'active',
      isNewUserPage: true,
    },
    {
      path: '/users/pending',
      title: 'Pending Invitations',
      key: 'pending',
    },
    {
      path: '/users/disabled',
      title: 'Disabled Users',
      key: 'disabled',
    },
  ], {
    template: '<div class="container"><page-users-list on-error="handleError"></page-users-list></div>',
    reloadOnSearch: false,
    controller($scope, $exceptionHandler) {
      'ngInject';

      $scope.handleError = $exceptionHandler;
    },
  });

  const profileRoutes = routesToAngularRoutes([
    {
      path: '/users/me',
      title: 'Account',
      key: 'users',
    },
    {
      path: '/users/:userId',
      title: 'Users',
      key: 'users',
    },
  ], {
    reloadOnSearch: false,
    template: '<settings-screen><page-user-profile on-error="handleError"></page-user-profile></settings-screen>',
    controller($scope, $exceptionHandler) {
      'ngInject';

      $scope.handleError = $exceptionHandler;
    },
  });

  const mfaRoutes = routesToAngularRoutes([
    {
      path: '/:org_slug/users/me/mfa',
      title: 'MFA Settings',
      key: 'users',
    },
  ], {
    reloadOnSearch: false,
    template: '<settings-screen><page-mfa-settings on-error="handleError"></page-mfa-settings></settings-screen>',
    controller($scope, $exceptionHandler) {
      'ngInject';

      $scope.handleError = $exceptionHandler;
    },
  });

  return extend(listRoutes, profileRoutes, mfaRoutes);
}

init.init = true;
