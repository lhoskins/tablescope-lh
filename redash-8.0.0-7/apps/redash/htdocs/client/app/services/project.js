export let Project = {}; // eslint-disable-line import/no-mutable-exports

function ProjectService($resource) {
  const actions = {
    get: { method: 'GET', cache: false, isArray: false },
    query: { method: 'GET', cache: false, isArray: true },
    members: { method: 'GET', cache: false, isArray: true, url: 'api/projects/:id/members' },
    addMember: { method: 'POST', url: 'api/projects/:id/members' },
    removeMember: { method: 'DELETE', url: 'api/projects/:id/members/:userId' },
    dataSources: { method: 'GET', cache: false, isArray: true, url: 'api/projects/:id/data_sources' },
    addDataSource: { method: 'POST', url: 'api/projects/:id/data_sources' },
    removeDataSource: { method: 'DELETE', url: 'api/projects/:id/data_sources/:dataSourceId' },
    updateDataSource: { method: 'POST', url: 'api/projects/:id/data_sources/:dataSourceId' },
  };

  return $resource('api/projects/:id', { id: '@id' }, actions);
}

export default function init(ngModule) {
  ngModule.factory('Project', ProjectService);

  ngModule.run(($injector) => {
    Project = $injector.get('Project');
  });
}

init.init = true;
