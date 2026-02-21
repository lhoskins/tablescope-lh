import ngModule from '@/config';
import dropzoneDirective from './directives/dropzoneDirective';
import UserOwnedProjects from './pages/projects/UserOwnedProjects'; // Import the React component
import MFASettingsPage from './pages/users/MFASettingsPage'; // Import MFA Settings page

// Register the directive with the main AngularJS module
dropzoneDirective(ngModule);

// Register the React component with AngularJS
ngModule.component('userOwnedProjects', UserOwnedProjects);
ngModule.component('pageMfaSettings', MFASettingsPage);

// Configure AngularJS routes
ngModule.config(($routeProvider, $locationProvider, $compileProvider, uiSelectConfig) => {
  'ngInject';

  // AngularJS routing configuration
  $routeProvider.when('/my_projects', {
    template: '<user-owned-projects http="$http"></user-owned-projects>', // Angular component wrapper for React
  });

  // Default route behavior for unknown paths
  $routeProvider.otherwise({
    redirectTo: '/',
  });

  // Enable HTML5 mode for cleaner URLs
  $locationProvider.html5Mode(true);

  // Configure AngularJS for sanitization
  $compileProvider.debugInfoEnabled(true);
  $compileProvider.aHrefSanitizationWhitelist(/^\s*(https?|data|tel|sms|mailto|javascript):/);

  // Set theme for ui-select
  uiSelectConfig.theme = 'bootstrap';
});

// Update ui-select's template to use Font-Awesome instead of glyphicon.
ngModule.run(($templateCache) => {
  const templateName = 'bootstrap/match.tpl.html';
  let template = $templateCache.get(templateName);
  template = template.replace('glyphicon glyphicon-remove', 'fa fa-remove');
  $templateCache.put(templateName, template);
});

export default ngModule;
