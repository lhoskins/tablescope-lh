/* eslint-disable react/prop-types */
import React from 'react';
import { react2angular } from 'react2angular';

import Button from 'antd/lib/button';
import { Paginator } from '@/components/Paginator';

import { wrap as liveItemsList, ControllerType } from '@/components/items-list/ItemsList';
import { ResourceItemsSource } from '@/components/items-list/classes/ItemsSource';
import { StateStorage } from '@/components/items-list/classes/StateStorage';

import LoadingState from '@/components/items-list/components/LoadingState';
import EmptyState from '@/components/items-list/components/EmptyState';
import ItemsTable, { Columns } from '@/components/items-list/components/ItemsTable';

import CreateProjectDialog from '@/components/projects/CreateProjectDialog';
import DeleteProjectButton from '@/components/projects/DeleteProjectButton';

import { Project } from '@/services/project';
import settingsMenu from '@/services/settingsMenu';
import { currentUser } from '@/services/auth';
import navigateTo from '@/services/navigateTo';
import { routesToAngularRoutes } from '@/lib/utils';

class ProjectsList extends React.Component {
  static propTypes = {
    controller: ControllerType.isRequired,
  };

  listColumns = [
    Columns.custom(
      (text, project) => (
        <div>
          <a href={`projects/${project.id}`}>{project.name}</a>
          {project.type === 'builtin' && (
            <span className="label label-default m-l-10">built-in</span>
          )}
        </div>
      ),
      {
        field: 'name',
        width: null,
      },
    ),
    Columns.custom(
      (text, project) => (
        <Button.Group>
          <Button href={`projects/${project.id}`}>Members</Button>
          {currentUser.isAdmin && (
            <Button href={`projects/${project.id}/data_sources`}>Data Sources</Button>
          )}
        </Button.Group>
      ),
      {
        width: '1%',
        className: 'text-nowrap',
      },
    ),
    Columns.custom(
      (text, project) => {
        const canRemove = project.type !== 'builtin';
        return (
          <DeleteProjectButton
            className="w-100"
            disabled={!canRemove}
            project={project}
            title={canRemove ? null : 'Cannot delete built-in project'}
            onClick={() => this.onProjectDeleted()}
          >
            Delete
          </DeleteProjectButton>
        );
      },
      {
        width: '1%',
        className: 'text-nowrap p-l-0',
        isAvailable: () => currentUser.isAdmin,
      },
    ),
  ];

  /** Create-Project flow */
  createProject = () => {
    CreateProjectDialog.showModal().result.then(project => {
      project.$save().then(newProject => {
        // 1️⃣ Dispatch before we navigate so the sidebar is still mounted
        console.log('[ProjectList] dispatching project-created', newProject);
        document.dispatchEvent(
          new CustomEvent('project-created', { detail: newProject }),
        );

        // 2️⃣ Navigate on next tick (still effectively immediate)
        setTimeout(() => {
          console.log('[ProjectList] navigateTo →', `/projects/${newProject.id}`);
          navigateTo(`/projects/${newProject.id}`);
        }, 0);
      });
    });
  };

  onProjectDeleted = () => {
    this.props.controller.updatePagination({ page: 1 });
    this.props.controller.update();
  };

  render() {
    const { controller } = this.props;

    return (
      <div data-test="ProjectList">
        <div className="m-b-15">
          <Button type="primary" onClick={this.createProject}>
            <i className="fa fa-plus m-r-5" />
            New Project
          </Button>
        </div>

        {!controller.isLoaded && <LoadingState />}
        {controller.isLoaded && controller.isEmpty && <EmptyState />}
        {controller.isLoaded && !controller.isEmpty && (
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
        )}
      </div>
    );
  }
}

/* ---------------- Angular bootstrap ---------------- */

export default function init(ngModule) {
  settingsMenu.add({
    permission: 'list_users',
    title: 'Projects',
    path: 'projects',
    order: 3,
  });

  ngModule.component(
    'pageProjectsList',
    react2angular(
      liveItemsList(
        ProjectsList,
        new ResourceItemsSource({
          isPlainList: true,
          getRequest() {
            return {};
          },
          getResource() {
            return Project.query.bind(Project);
          },
          getItemProcessor() {
            return item => new Project(item);
          },
        }),
        new StateStorage({ orderByField: 'name', itemsPerPage: 10 }),
      ),
    ),
  );

  return routesToAngularRoutes(
    [
      {
        path: '/projects',
        title: 'Projects',
        key: 'projects',
      },
    ],
    {
      reloadOnSearch: false,
      template:
        '<settings-screen><page-projects-list on-error="handleError"></page-projects-list></settings-screen>',
      controller($scope, $exceptionHandler) {
        'ngInject';

        $scope.handleError = $exceptionHandler;
      },
    },
  );
}

init.init = true;
