/* eslint-disable import/first */

/**
 * Global boot-strap for Redash front-end (v8) – customized to
 * register trace-level logging and new React shells.
 */

import 'core-js/fn/typed/array-buffer';
import '@/assets/images/avatar.svg';

import * as Pace from 'pace-progress';
import debug from 'debug';
import angular from 'angular';
import ngSanitize from 'angular-sanitize';
import ngRoute from 'angular-route';
import ngResource from 'angular-resource';
import uiBootstrap from 'angular-ui-bootstrap';
import uiSelect from 'ui-select';
import ngMessages from 'angular-messages';
import ngUpload from 'angular-base64-upload';
import vsRepeat from 'angular-vs-repeat';
import 'brace';
import 'angular-ui-ace';
import 'angular-resizable';

import moment from 'moment';
import { each, isFunction, extend } from 'lodash';
import { react2angular } from 'react2angular';

import '@/lib/sortable';
import DialogWrapper from '@/components/DialogWrapper';
import organizationStatus from '@/services/organizationStatus';

import * as filters from '@/filters';
import registerDirectives from '@/directives';
import dropzoneDirective from '@/directives/dropzoneDirective';
import markdownFilter from '@/filters/markdown';
import dateTimeFilter from '@/filters/datetime';
import './antd-spinner';

/* -- TRACE-LEVEL LOGGING SETUP -- */
// Send all debug(...) output through console.trace for full-stack insight
debug.log = console.trace.bind(console);
// Turn on every `redash:*` namespace
debug.enable('redash:*');
const logger = debug('redash:config');
logger('🛠️ Trace-level logging enabled');

/* React components we surface to Angular */
import NavigationPane from '@/pages/NavigationPane/NavigationPane';
import ProjectDetailPage from '@/pages/NavigationPane/ProjectDetailPage';
/* ensures TSQueryEditor is registered globally */
import '@/components/TSQueryEditor';

/* ----------------------------------------------------------------------------- */
/*  Pace – ignore “?search-string” changes so SPA navigation feels smoother        */
/* ----------------------------------------------------------------------------- */
Pace.options.shouldHandlePushState = (from, to) => {
  const [a] = from.split('?');
  const [b] = to.split('?');
  return a !== b;
};

/* nicer relative-time strings */
moment.updateLocale('en', {
  relativeTime: {
    future: '%s',
    past: '%s',
    s: 'just now',
    m: 'a minute ago',
    mm: '%d minutes ago',
    h: 'an hour ago',
    hh: '%d hours ago',
    d: 'a day ago',
    dd: '%d days ago',
    M: 'a month ago',
    MM: '%d months ago',
    y: 'a year ago',
    yy: '%d years ago',
  },
});

/* --------------------------------------------------------------------------- */
/*  AngularJS module + deps                                                    */
/* --------------------------------------------------------------------------- */
const ngDependencies = [
  ngRoute,
  ngResource,
  ngSanitize,
  uiBootstrap,
  ngMessages,
  uiSelect,
  'ui.ace',
  ngUpload,
  'angularResizable',
  vsRepeat,
  'ui.sortable',
];

const ngModule = angular.module('app', ngDependencies);

/* --------------------------------------------------------------------------- */
/* Decorate $log to add a .trace() level                                        */
/* --------------------------------------------------------------------------- */
ngModule.config(['$provide', function($provide) {
  $provide.decorator('$log', ['$delegate', function($delegate) {
    // Mirror trace to debug under the hood
    $delegate.trace = function() {
      $delegate.debug.apply($delegate, arguments);
    };
    return $delegate;
  }]);
}]);

/* --------------------------------------------------------------------------- */
/* Generic helper to auto-register any “*.init = true” modules                 */
/* --------------------------------------------------------------------------- */
function registerAll(requireCtx) {
  const modules = requireCtx
    .keys()
    .map(requireCtx)
    .map(m => m.default);

  return modules
    .filter(isFunction)
    .filter(f => f.init)
    .map(f => f(ngModule));
}

/* --------------------------------------------------------------------------- */
/* Asset loader – images go through webpack so urls are hashed correctly       */
/* --------------------------------------------------------------------------- */
(function requireImages() {
  const ctx = require.context('@/assets/images/', true, /\.(png|jpe?g|gif|svg)$/);
  ctx.keys().forEach(ctx);
}());

/* --------------------------------------------------------------------------- */
/* Dynamic registration of components / pages / services / etc.               */
/* --------------------------------------------------------------------------- */
function registerComponents() {
  registerAll(require.context('@/components', true, /^((?![\/.]test[\./]).)*\.jsx?$/));
}
function registerServices() {
  registerAll(require.context('@/services', true, /^((?![\/.]test[\./]).)*\.js$/));
}
function registerExtensions() {
  registerAll(require.context('extensions', true, /^((?![\/.]test[\./]).)*\.jsx?$/));
}
function registerVisualizations() {
  registerAll(require.context('@/visualizations', true, /^((?![\/.]test[\./]).)*\.jsx?$/));
}

/* --------------------------------------------------------------------------- */
/* Pages return their own route definitions. We collect & register them here   */
/* --------------------------------------------------------------------------- */
function registerPages() {
  const ctx = require.context('@/pages', true, /^((?![\/.]test[\./]).)*\.jsx?$/);
  const routesCollections = registerAll(ctx);

  routesCollections.forEach((routes) => {
    ngModule.config(['$routeProvider', ($routeProvider) => {
      each(routes, (route, path) => {
        logger('Registering route: %s', path);
        route.authenticated = true;
        route.resolve = extend(
          { __organizationStatus: () => organizationStatus.refresh() },
          route.resolve,
        );
        $routeProvider.when(path, route);
      });
    }]);
  });
}

/* --------------------------------------------------------------------------- */
/*  React components exposed to Angular                                        */
/* --------------------------------------------------------------------------- */
ngModule.component('navigationPane', react2angular(NavigationPane, ['http', 'onProjectSelected']));
ngModule.component('projectDetailPage', react2angular(ProjectDetailPage));

/* --------------------------------------------------------------------------- */
/*  Manual route stubs for our React shells & TSQuery pages                    */
/* --------------------------------------------------------------------------- */
ngModule.config(['$routeProvider', ($routeProvider) => {
  $routeProvider.when('/NavigationPane', {
    template: `
      <app-header></app-header>
      <navigation-pane http="$http"></navigation-pane>
    `,
    controller($scope, $exceptionHandler) {
      'ngInject';
      $scope.handleError = $exceptionHandler;
    },
  });

  // TSQuery route with proper resolvers to ensure query data is loaded before controller runs
  $routeProvider.when('/tsqueries/:queryId', {
    templateUrl: 'TSquery.html',
    controller: 'TSQueryViewCtrl',
    layout: 'fixed',
    reloadOnSearch: false,
    resolve: {
      __organizationStatus: () => organizationStatus.refresh(),
      query: ['Query', '$route', (Query, $route) => {
        return Query.get({ id: $route.current.params.queryId }).$promise;
      }],
      dataSources: ['DataSource', (DataSource) => {
        return DataSource.query().$promise;
      }],
    },
  });

  $routeProvider.otherwise({
    resolve: {
      error: () => { const e = { status: 404 }; throw e; },
    },
  });
}]);

/* --------------------------------------------------------------------------- */
/*  Global filters                                                             */
/* --------------------------------------------------------------------------- */
each(filters, (fn, name) => ngModule.filter(name, () => fn));

/* --------------------------------------------------------------------------- */
/*  Initialise everything                                                      */
/* --------------------------------------------------------------------------- */
registerDirectives(ngModule);
dropzoneDirective(ngModule);
registerServices();
markdownFilter(ngModule);
dateTimeFilter(ngModule);
registerComponents();
registerPages();
registerExtensions();
registerVisualizations();

/* Provide Angular’s $q to DialogWrapper for React modals */
ngModule.run(['$q', ($q) => { DialogWrapper.Promise = $q; }]);

export default ngModule;
