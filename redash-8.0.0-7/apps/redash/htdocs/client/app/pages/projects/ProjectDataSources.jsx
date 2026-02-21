import { filter, map, includes } from 'lodash';
import React from 'react';
import { react2angular } from 'react2angular';
import Button from 'antd/lib/button';
import Dropdown from 'antd/lib/dropdown';
import Menu from 'antd/lib/menu';
import Icon from 'antd/lib/icon';

import { Paginator } from '@/components/Paginator';

import { wrap as liveItemsList, ControllerType } from '@/components/items-list/ItemsList';
import { ResourceItemsSource } from '@/components/items-list/classes/ItemsSource';
import { StateStorage } from '@/components/items-list/classes/StateStorage';

import LoadingState from '@/components/items-list/components/LoadingState';
import ItemsTable, { Columns } from '@/components/items-list/components/ItemsTable';
import SelectItemsDialog from '@/components/SelectItemsDialog';
import { DataSourcePreviewCard } from '@/components/PreviewCard';

import ProjectName from '@/components/projects/ProjectName';
import ListItemAddon from '@/components/projects/ListItemAddon';
import Sidebar from '@/components/projects/DetailsPageSidebar';
import Layout from '@/components/layouts/ContentWithSidebar';
import PermissionGuard from '@/components/PermissionGuard';

import notification from '@/services/notification';
import { currentUser } from '@/services/auth';
import { Project } from '@/services/project';
import { DataSource } from '@/services/data-source';
import navigateTo from '@/services/navigateTo';
import { routesToAngularRoutes } from '@/lib/utils';

class ProjectDataSources extends React.Component {
  static propTypes = {
    controller: ControllerType.isRequired,
  };

  projectId = parseInt(this.props.controller.params.projectId, 10);

  project = null;

  sidebarMenu = [
    {
      key: 'users',
      href: `projects/${this.projectId}`,
      title: 'Members',
    },
    {
      key: 'datasources',
      href: `projects/${this.projectId}/data_sources`,
      title: 'Data Sources',
      isAvailable: () => currentUser.isAdmin,
    },
  ];

  listColumns = [
    Columns.custom((text, datasource) => (
      <DataSourcePreviewCard dataSource={datasource} withLink />
    ), {
      title: 'Name',
      field: 'name',
      width: null,
    }),
    Columns.custom((text, datasource) => {
      const menu = (
        <Menu
          selectedKeys={[datasource.view_only ? 'viewonly' : 'full']}
          onClick={item => this.setDataSourcePermissions(datasource, item.key)}
        >
          <Menu.Item key="full">Full Access</Menu.Item>
          <Menu.Item key="viewonly">View Only</Menu.Item>
        </Menu>
      );

      return (
        <PermissionGuard 
          permission="assign_datasource_to_project"
          resource={{ type: 'project', id: this.projectId }}
        >
          <Dropdown trigger={['click']} overlay={menu}>
            <Button className="w-100">{datasource.view_only ? 'View Only' : 'Full Access'}<Icon type="down" /></Button>
          </Dropdown>
        </PermissionGuard>
      );
    }, {
      width: '1%',
      className: 'p-r-0',
    }),
    Columns.custom((text, datasource) => (
      <PermissionGuard 
        permission="remove_datasource_from_project"
        resource={{ type: 'project', id: this.projectId }}
      >
        <Button className="w-100" type="danger" onClick={() => this.removeProjectDataSource(datasource)}>Remove</Button>
      </PermissionGuard>
    ), {
      width: '1%',
    }),
  ];

  componentDidMount() {
    Project.get({ id: this.projectId }).$promise
      .then((project) => {
        this.project = project;
        this.forceUpdate();
      })
      .catch((error) => {
        this.props.controller.handleError(error);
      });
  }

  removeProjectDataSource = (datasource) => {
    Project.removeDataSource({ id: this.projectId, dataSourceId: datasource.id }).$promise
      .then(() => {
        this.props.controller.updatePagination({ page: 1 });
        this.props.controller.update();
      })
      .catch(() => {
        notification.error('Failed to remove data source from project.');
      });
  };

  setDataSourcePermissions = (datasource, permission) => {
    const viewOnly = permission !== 'full';

    Project.updateDataSource({ id: this.projectId, dataSourceId: datasource.id }, { view_only: viewOnly }).$promise
      .then(() => {
        datasource.view_only = viewOnly;
        this.forceUpdate();
      })
      .catch(() => {
        notification.error('Failed change data source permissions.');
      });
  };

addDataSources = () => {
  const allDataSources = DataSource.query().$promise;
  const alreadyAddedDataSources = map(this.props.controller.allItems, ds => ds.id);

  SelectItemsDialog.showModal({
    dialogTitle: 'Add Data Sources',
    inputPlaceholder: 'Search data sources...',
    selectedItemsTitle: 'New Data Sources',
    searchItems: (searchTerm) => {
      searchTerm = searchTerm.toLowerCase();
      return allDataSources.then(items => filter(items, ds => ds.name.toLowerCase().includes(searchTerm) && ds.owner === currentUser.id));
    },
    renderItem: (item, { isSelected }) => {
      const alreadyInProject = includes(alreadyAddedDataSources, item.id);
      return {
        content: (
          <DataSourcePreviewCard dataSource={item}>
            <ListItemAddon isSelected={isSelected} alreadyInProject={alreadyInProject} />
          </DataSourcePreviewCard>
        ),
        isDisabled: alreadyInProject,
        className: isSelected || alreadyInProject ? 'selected' : '',
      };
    },
    renderStagedItem: (item, { isSelected }) => ({
      content: (
        <DataSourcePreviewCard dataSource={item}>
          <ListItemAddon isSelected={isSelected} isStaged />
        </DataSourcePreviewCard>
      ),
    }),
    save: (items) => {
      const promises = map(items, ds => Project.addDataSource({ id: this.projectId, data_source_id: ds.id })
        .$promise.then((response) => {
          // Differentiate based on the API response
          if (response.action === 'request') {
            // Show success message when an approval request is created
            notification.success('Successfully requested data source to be added.');
          } else if (response.action === 'add') {
            // Show success message when a data source is added directly
            notification.success('Data source successfully added to the project.');
          } else if (response.action === 'already_exists') {
            // Handle cases where the data source is already added
            notification.info('Data source is already added to the project.');
          }
        })
        .catch(() => {
          notification.error('Failed to request data source addition.');
        }));

      return Promise.all(promises);
    },
  }).result.finally(() => {
    this.props.controller.update();
  });
};

render() {
  const { controller } = this.props;
  return (
    <div data-test="Project">
      <ProjectName className="d-block m-t-0 m-b-15" project={this.project} onChange={() => this.forceUpdate()} />
      <Layout>
        <Layout.Sidebar>
          <Sidebar
            controller={controller}
            project={this.project}
            items={this.sidebarMenu}
            canAddDataSources={currentUser.isAdmin}
            onAddDataSourcesClick={this.addDataSources}
            onProjectDeleted={() => navigateTo('/projects', true)}
          />
        </Layout.Sidebar>
        <Layout.Content>
          {!controller.isLoaded && <LoadingState className="" />}
          {controller.isLoaded && controller.isEmpty && (
          <div className="text-center">
            <p>
                  There are no data sources in this project yet.
            </p>
            <PermissionGuard 
              permission="assign_datasource_to_project"
              resource={{ type: 'project', id: this.projectId }}
            >
              <Button type="primary" onClick={this.addDataSources}>
                <i className="fa fa-plus m-r-5" />Add Data Sources
              </Button>
            </PermissionGuard>
          </div>
          )}
          {
              controller.isLoaded && !controller.isEmpty && (
                <div className="table-responsive">
                  <ItemsTable
                    items={controller.pageItems}
                    columns={this.listColumns}
                    showHeader={false}
                    context={this.actions}
                    orderByField={controller.orderByField}
                    orderByReverse={controller.orderByReverse}
                    toggleSorting={controller.toggleSorting}
                  />
                  <Paginator
                    totalCount={controller.totalItemsCount}
                    itemsPerPage={controller.itemsPerPage}
                    page={controller.page}
                    onChange={page => controller.updatePagination({ page })}
                  />
                </div>
              )
            }
        </Layout.Content>
      </Layout>
    </div>
  );
}
}

export default function init(ngModule) {
  ngModule.component('pageProjectDataSources', react2angular(liveItemsList(
    ProjectDataSources,
    new ResourceItemsSource({
      isPlainList: true,
      getRequest(unused, { params: { projectId } }) {
        return { id: projectId };
      },
      getResource() {
        return Project.dataSources.bind(Project);
      },
      getItemProcessor() {
        return (item => new DataSource(item));
      },
    }),
    new StateStorage({ orderByField: 'name' }),
  )));

  return routesToAngularRoutes([
    {
      path: '/projects/:projectId/data_sources',
      title: 'Project Data Sources',
      key: 'datasources',
    },
  ], {
    reloadOnSearch: false,
    template: '<settings-screen><page-project-data-sources on-error="handleError"></page-project-data-sources></settings-screen>',
    controller($scope, $exceptionHandler) {
      'ngInject';

      $scope.handleError = $exceptionHandler;
    },
  });
}

init.init = true;
