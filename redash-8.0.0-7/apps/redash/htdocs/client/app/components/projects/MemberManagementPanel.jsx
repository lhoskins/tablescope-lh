import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import Button from 'antd/lib/button';
import Table from 'antd/lib/table';
import Alert from 'antd/lib/alert';
import notification from '@/services/notification';
import MemberRoleRow from './MemberRoleRow';
import AddMemberModal from './AddMemberModal';
import './MemberManagementPanel.less';

/**
 * MemberManagementPanel Component
 * 
 * Main panel for managing project members and roles.
 * Displays member table with role checkboxes and Add Member button.
 */
function MemberManagementPanel({ projectId, userRole }) {
  const [members, setMembers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [updatingMemberId, setUpdatingMemberId] = useState(null);
  const [showAddMemberModal, setShowAddMemberModal] = useState(false);

  useEffect(() => {
    loadMembers();
  }, [projectId]);

  const loadMembers = async () => {
    setLoading(true);
    try {
      const response = await fetch(`api/projects/${projectId}/members`, {
        credentials: 'same-origin',
      });

      if (!response.ok) {
        throw new Error('Failed to load members');
      }

      const data = await response.json();
      setMembers(data);
    } catch (error) {
      notification.error('Failed to load project members');
      console.error('Error loading members:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleRoleChange = async (userId, newRole) => {
    setUpdatingMemberId(userId);

    try {
      const response = await fetch(`api/projects/${projectId}/members/${userId}/role`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify({ role: newRole }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to update role');
      }

      const updatedMember = await response.json();

      // Update local state
      setMembers((prevMembers) =>
        prevMembers.map((m) =>
          m.user_id === userId ? { ...m, role: updatedMember.role } : m
        )
      );
    } finally {
      setUpdatingMemberId(null);
    }
  };

  const handleMemberAdded = (newMember) => {
    setMembers((prevMembers) => [...prevMembers, newMember]);
    setShowAddMemberModal(false);
  };

  // Check if user can manage members
  console.log('[MemberManagementPanel] User role:', userRole, 'Type:', typeof userRole);
  const canManage = userRole === 'owner' || userRole === 'admin';
  const isViewOnly = userRole === 'designer' || userRole === 'member';
  console.log('[MemberManagementPanel] canManage:', canManage, 'isViewOnly:', isViewOnly);

  const columns = [
    {
      title: (
        <div className="member-table-header">
          <i className="fa fa-user" style={{ marginRight: 8 }} />
          Name
        </div>
      ),
      key: 'name',
      width: '30%',
    },
    {
      title: 'Project Owner',
      key: 'owner',
      align: 'center',
      width: '17.5%',
    },
    {
      title: 'Project Admin',
      key: 'admin',
      align: 'center',
      width: '17.5%',
    },
    {
      title: 'Designer',
      key: 'designer',
      align: 'center',
      width: '17.5%',
    },
    {
      title: 'Project Member',
      key: 'member',
      align: 'center',
      width: '17.5%',
    },
  ];

  return (
    <div className="member-management-panel">
      <div className="panel-header">
        <div className="header-content">
          <h2>Project Members</h2>
          <p className="header-description">
            Invite or manage your project's members.
          </p>
        </div>
        {canManage && (
          <Button
            type="primary"
            icon={<i className="fa fa-plus" />}
            onClick={() => setShowAddMemberModal(true)}
          >
            Add Member
          </Button>
        )}
      </div>

      {isViewOnly && (
        <Alert
          message="View Only"
          description="You can view project members but cannot make changes. Only project owners and admins can manage members."
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      <div className="member-table-container">
        <Table
          dataSource={members}
          columns={columns}
          loading={loading}
          rowKey="user_id"
          pagination={false}
          components={{
            body: {
              row: ({ children, ...props }) => {
                const member = members.find((m) => m.user_id === props['data-row-key']);
                if (!member) return <tr {...props}>{children}</tr>;

                return (
                  <MemberRoleRow
                    member={member}
                    currentUserRole={userRole}
                    onRoleChange={handleRoleChange}
                    isUpdating={updatingMemberId === member.user_id}
                  />
                );
              },
            },
          }}
        />
      </div>

      {showAddMemberModal && (
        <AddMemberModal
          projectId={projectId}
          visible={showAddMemberModal}
          currentUserRole={userRole}
          onClose={() => setShowAddMemberModal(false)}
          onMemberAdded={handleMemberAdded}
        />
      )}
    </div>
  );
}

MemberManagementPanel.propTypes = {
  projectId: PropTypes.number.isRequired,
  userRole: PropTypes.oneOf(['owner', 'admin', 'designer', 'member']).isRequired,
};

export default MemberManagementPanel;
