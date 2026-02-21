import { includes, map } from 'lodash';
import React from 'react';
import { react2angular } from 'react2angular';
import Button from 'antd/lib/button';

import { Paginator } from '@/components/Paginator';

import { wrap as liveItemsList, ControllerType } from '@/components/items-list/ItemsList';
import { ResourceItemsSource } from '@/components/items-list/classes/ItemsSource';
import { StateStorage } from '@/components/items-list/classes/StateStorage';

import LoadingState from '@/components/items-list/components/LoadingState';
import ItemsTable, { Columns } from '@/components/items-list/components/ItemsTable';
import SelectItemsDialog from '@/components/SelectItemsDialog';
import { UserPreviewCard } from '@/components/PreviewCard';

import ProjectName from '@/components/projects/ProjectName';
import ListItemAddon from '@/components/projects/ListItemAddon';
import Sidebar from '@/components/projects/DetailsPageSidebar';
import Layout from '@/components/layouts/ContentWithSidebar';
import PermissionGuard from '@/components/PermissionGuard';
import OwnerBadge from '@/components/OwnerBadge';
import RoleBadge from '@/components/RoleBadge';

import notification from '@/services/notification';
import { currentUser } from '@/services/auth';
import { Project } from '@/services/project';
import { User } from '@/services/user';
import navigateTo from '@/services/navigateTo';
import { routesToAngularRoutes } from '@/lib/utils';

class ProjectMembers extends React.Component {
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
    Columns.custom((text, user) => (
      <UserPreviewCard user={user} withLink />
    ), {
      title: 'Name',
      field: 'name',
      width: null,
    }),
    Columns.custom((text, user) => {
      if (!this.project) {
        return null;
      }
      
      // Show role badge for the member
      const memberRole = user.project_role || 'member';
      const isOwner = this.project.user_id === user.id;
      
      return (
        <div>
          {isOwner && <OwnerBadge isOwner={true} className="m-r-5" />}
          {memberRole !== 'member' && <RoleBadge role={memberRole} />}
        </div>
      );
    }, {
      title: 'Role',
      field: 'role',
      width: '15%',
    }),
    Columns.custom((text, user) => {
      if (!this.project) {
        return null;
      }

      // cannot remove self from built-in projects
      if ((this.project.type === 'builtin') && (currentUser.id === user.id)) {
        return null;
      }
      
      return (
        <PermissionGuard 
          permission="remove_project_member"
          resource={{ type: 'project', id: this.projectId }}
        >
          <Button className="w-100" type="danger" onClick={event => this.removeProjectMember(event, user)}>
            Remove
          </Button>
        </PermissionGuard>
      );
    }, {
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

  removeProjectMember = (event, user) => Project.removeMember({ id: this.projectId, userId: user.id }).$promise
    .then(() => {
      this.props.controller.updatePagination({ page: 1 });
      this.props.controller.update();
    })
    .catch(() => {
      notification.error('Failed to remove member from project.');
    });

  addMembers = () => {
    const alreadyAddedUsers = map(this.props.controller.allItems, u => u.id);
    SelectItemsDialog.showModal({
      dialogTitle: 'Add Members',
      inputPlaceholder: 'Search users...',
      selectedItemsTitle: 'New Members',
      searchItems: searchTerm => User.query({ q: searchTerm }).$promise.then(({ results }) => results),
      renderItem: (item, { isSelected }) => {
        const alreadyInProject = includes(alreadyAddedUsers, item.id);
        return {
          content: (
            <UserPreviewCard user={item}>
              <ListItemAddon isSelected={isSelected} alreadyInProject={alreadyInProject} />
            </UserPreviewCard>
          ),
          isDisabled: alreadyInProject,
          className: isSelected || alreadyInProject ? 'selected' : '',
        };
      },
      renderStagedItem: (item, { isSelected }) => ({
        content: (
          <UserPreviewCard user={item}>
            <ListItemAddon isSelected={isSelected} isStaged />
          </UserPreviewCard>
        ),
      }),
      save: (items) => {
        const promises = map(items, u => 
          Project.addMember({ id: this.projectId }, { user_id: u.id }).$promise
            .catch(error => {
              // Ignore "already a member" errors (HTTP 200 or 400 with specific message)
              if (error.status === 400 && error.data && error.data.message && 
                  error.data.message.includes('already a member')) {
                return Promise.resolve(); // Treat as success
              }
              throw error; // Re-throw other errors
            })
        );
        return Promise.all(promises);
      },
    }).result.finally(() => {
      this.props.controller.update();
    });
  };

  render() {
    const { controller } = this.props;
    const isOwner = this.project && this.project.user_id === currentUser.id;
    
    return (
      <div data-test="Project">
        <div className="d-flex align-items-center m-b-15">
          <ProjectName className="d-block m-t-0 m-b-0" project={this.project} onChange={() => this.forceUpdate()} />
          {isOwner && <OwnerBadge isOwner={true} className="m-l-10" />}
        </div>
        <Layout>
          <Layout.Sidebar>
            <Sidebar
              controller={controller}
              project={this.project}
              items={this.sidebarMenu}
              canAddMembers={currentUser.isAdmin}
              onAddMembersClick={this.addMembers}
              onProjectDeleted={() => navigateTo('/projects', true)}
            />
          </Layout.Sidebar>
          <Layout.Content>
            {!controller.isLoaded && <LoadingState className="" />}
            {controller.isLoaded && controller.isEmpty && (
              <div className="text-center">
                <p>
                  There are no members in this project yet.
                </p>
                <PermissionGuard 
                  permission="add_project_member"
                  resource={{ type: 'project', id: this.projectId }}
                >
                  <Button type="primary" onClick={this.addMembers}>
                    <i className="fa fa-plus m-r-5" />Add Members
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
                    showHeader={true}
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
  ngModule.component('pageProjectMembers', react2angular(liveItemsList(
    ProjectMembers,
    new ResourceItemsSource({
      isPlainList: true,
      getRequest(unused, { params: { projectId } }) {
        return { id: projectId };
      },
      getResource() {
        return Project.members.bind(Project);
      },
      getItemProcessor() {
        return (item => {
          // Handle both member objects ({ user: {...} }) and direct user objects
          // Member objects come from Project.members API which returns { user_id, user: {...}, added_by: {...} }
          // Direct user objects may come from other sources for backward compatibility
          const userData = item.user || item;
          return new User(userData);
        });
      },
    }),
    new StateStorage({ orderByField: 'name' }),
  )));

  return routesToAngularRoutes([
    {
      path: '/projects/:projectId',
      title: 'Project Members',
      key: 'users',
    },
  ], {
    reloadOnSearch: false,
    template: '<settings-screen><page-project-members on-error="handleError"></page-project-members></settings-screen>',
    controller($scope, $exceptionHandler) {
      'ngInject';

      $scope.handleError = $exceptionHandler;
    },
  });
}

init.init = true;
