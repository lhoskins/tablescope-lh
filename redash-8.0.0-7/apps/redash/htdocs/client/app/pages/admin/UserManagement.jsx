import React, { useState, useEffect } from 'react';
import { react2angular } from 'react2angular';
import Button from 'antd/lib/button';
import Select from 'antd/lib/select';
import Table from 'antd/lib/table';
import Tag from 'antd/lib/tag';
import Modal from 'antd/lib/modal';
import notification from '@/services/notification';
import { User } from '@/services/user';
import { currentUser } from '@/services/auth';
import PermissionGuard from '@/components/PermissionGuard';
import RoleBadge from '@/components/RoleBadge';
import { routesToAngularRoutes } from '@/lib/utils';
import settingsMenu from '@/services/settingsMenu';

const { Option } = Select;

function UserManagement() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [updatingUserId, setUpdatingUserId] = useState(null);

  useEffect(() => {
    loadUsers();
  }, []);

  const loadUsers = () => {
    setLoading(true);
    User.query().$promise
      .then((response) => {
        setUsers(response.results || []);
        setLoading(false);
      })
      .catch((error) => {
        notification.error('Failed to load users');
        console.error('Error loading users:', error);
        setLoading(false);
      });
  };

  const handleRoleChange = (userId, newRole) => {
    setUpdatingUserId(userId);
    
    // Call API to update user role
    fetch(`/api/users/${userId}/roles`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      credentials: 'same-origin',
      body: JSON.stringify({ role_type: newRole }),
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to update role');
        }
        return response.json();
      })
      .then(() => {
        notification.success('User role updated successfully');
        loadUsers();
      })
      .catch((error) => {
        notification.error('Failed to update user role');
        console.error('Error updating role:', error);
      })
      .finally(() => {
        setUpdatingUserId(null);
      });
  };

  const handleDisableMfa = (user) => {
    Modal.confirm({
      title: 'Disable MFA for User',
      content: (
        <div>
          <p>Are you sure you want to disable Multi-Factor Authentication for <strong>{user.name}</strong>?</p>
          <p>This action will:</p>
          <ul>
            <li>Remove their MFA enrollment</li>
            <li>Invalidate all backup codes</li>
            <li>Send a notification email to the user</li>
            <li>Require them to re-enroll before accessing privileged features</li>
          </ul>
          <p className="text-muted">This action will be logged in the audit log.</p>
        </div>
      ),
      okText: 'Disable MFA',
      okType: 'danger',
      cancelText: 'Cancel',
      onOk: () => {
        return fetch(`/api/users/${user.id}/mfa`, {
          method: 'DELETE',
          headers: {
            'Content-Type': 'application/json',
          },
          credentials: 'same-origin',
          body: JSON.stringify({
            reason: 'Admin disabled MFA via user management interface',
          }),
        })
          .then((response) => {
            if (!response.ok) {
              return response.json().then((data) => {
                throw new Error(data.message || 'Failed to disable MFA');
              });
            }
            return response.json();
          })
          .then(() => {
            notification.success(`MFA disabled successfully for ${user.name}`);
            loadUsers();
          })
          .catch((error) => {
            notification.error(`Failed to disable MFA: ${error.message}`);
          });
      },
      maskClosable: true,
      autoFocusButton: null,
    });
  };

  const columns = [
    {
      title: 'Name',
      dataIndex: 'name',
      key: 'name',
      render: (text, user) => (
        <div>
          <a href={`users/${user.id}`}>{text}</a>
          {user.id === currentUser.id && (
            <Tag color="blue" className="m-l-5">You</Tag>
          )}
        </div>
      ),
    },
    {
      title: 'Email',
      dataIndex: 'email',
      key: 'email',
    },
    {
      title: 'Role',
      dataIndex: 'role',
      key: 'role',
      render: (text, user) => {
        const userRole = user.role_type || 'default';
        return <RoleBadge role={userRole} />;
      },
    },
    {
      title: 'MFA',
      dataIndex: 'mfa_enabled',
      key: 'mfa_enabled',
      align: 'center',
      render: (mfaEnabled, user) => {
        if (mfaEnabled) {
          return (
            <div>
              <Tag color="green">Enabled</Tag>
              {user.id !== currentUser.id && (
                <Button
                  type="link"
                  size="small"
                  onClick={() => handleDisableMfa(user)}
                  style={{ padding: 0, marginLeft: 8 }}
                >
                  Disable
                </Button>
              )}
            </div>
          );
        }
        return <Tag color="default">Disabled</Tag>;
      },
    },
    {
      title: 'Projects',
      dataIndex: 'projects',
      key: 'projects',
      render: (projects) => {
        if (!projects || projects.length === 0) {
          return <span className="text-muted">None</span>;
        }
        return (
          <div>
            {projects.slice(0, 3).map((project) => (
              <Tag key={project.id}>
                <a href={`projects/${project.id}`}>{project.name}</a>
              </Tag>
            ))}
            {projects.length > 3 && (
              <Tag>+{projects.length - 3} more</Tag>
            )}
          </div>
        );
      },
    },
    {
      title: 'Actions',
      key: 'actions',
      render: (text, user) => {
        const userRole = user.role_type || 'default';
        const isCurrentUser = user.id === currentUser.id;
        
        return (
          <PermissionGuard permission="assign_role">
            <Select
              value={userRole}
              onChange={(value) => handleRoleChange(user.id, value)}
              disabled={isCurrentUser || updatingUserId === user.id}
              loading={updatingUserId === user.id}
              style={{ width: 180 }}
            >
              <Option value="default">Default</Option>
              <Option value="designer">Designer</Option>
              <Option value="organization_admin">Organization Admin</Option>
              {currentUser.hasPermission && currentUser.hasPermission('super_admin') && (
                <Option value="super_admin">Super Admin</Option>
              )}
            </Select>
          </PermissionGuard>
        );
      },
    },
  ];

  // Debug: Check current user permissions
  console.log('UserManagement - currentUser:', currentUser);
  console.log('UserManagement - currentUser.permissions:', currentUser.permissions);
  console.log('UserManagement - hasPermission("admin"):', currentUser.hasPermission ? currentUser.hasPermission('admin') : 'hasPermission not available');

  return (
    <div className="container">
      <div className="m-b-15">
        <h3>User Management</h3>
        <p className="text-muted">
          Manage users and their roles within your organization.
        </p>
      </div>

      <div className="bg-white tiled">
        <Table
          dataSource={users}
          columns={columns}
          loading={loading}
          rowKey="id"
          pagination={{
            pageSize: 20,
            showSizeChanger: true,
            showTotal: (total) => `Total ${total} users`,
          }}
        />
      </div>
    </div>
  );
}

export default function init(ngModule) {
  settingsMenu.add({
    permission: 'admin',
    title: 'User Management',
    path: 'admin/users',
    order: 5,
  });

  ngModule.component('pageUserManagement', react2angular(UserManagement));

  return routesToAngularRoutes([
    {
      path: '/admin/users',
      title: 'User Management',
      key: 'user_management',
    },
  ], {
    template: '<settings-screen><page-user-management></page-user-management></settings-screen>',
    controller($scope, $exceptionHandler) {
      'ngInject';
      $scope.handleError = $exceptionHandler;
    },
  });
}

init.init = true;
